from pathlib import Path

import pytest

from memory_core.workspace import MemoryWorkspace, UnsafeMemoryPathError


def test_discovers_root_and_every_markdown_file_under_memory(tmp_path: Path):
    # OpenClaw listMemoryFiles indexes every memory/**/*.md, not only daily files.
    (tmp_path / "MEMORY.md").write_text("# Long\n", encoding="utf-8")
    (tmp_path / "memory" / "projects").mkdir(parents=True)
    (tmp_path / "memory" / "2026-05-03.md").write_text("# Day\n", encoding="utf-8")
    (tmp_path / "memory" / "2026-05-03-1430.md").write_text("# Session\n", encoding="utf-8")
    (tmp_path / "memory" / "abcd-ef-gh.md").write_text("undated\n", encoding="utf-8")
    (tmp_path / "memory" / "projects" / "alpha.md").write_text("nested\n", encoding="utf-8")
    (tmp_path / "memory" / "notes.txt").write_text("skip\n", encoding="utf-8")

    workspace = MemoryWorkspace(tmp_path)

    assert [entry.rel_path for entry in workspace.discover_memory_files()] == [
        "MEMORY.md",
        "memory/2026-05-03-1430.md",
        "memory/2026-05-03.md",
        "memory/abcd-ef-gh.md",
        "memory/projects/alpha.md",
    ]


def test_discovery_lists_user_md_after_the_root_memory_file(tmp_path: Path):
    # OpenClaw host/internal.ts listMemoryFiles (28630a9a650 #114819): USER.md is indexed right
    # after MEMORY.md, before the memory/ walk, when it is a regular .md file.
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-09-29.md").write_text("day\n", encoding="utf-8")
    (tmp_path / "USER.md").write_text("- Prefer short replies.\n", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text("# Long\n", encoding="utf-8")

    assert [entry.rel_path for entry in MemoryWorkspace(tmp_path).discover_memory_files()] == [
        "MEMORY.md",
        "USER.md",
        "memory/2026-09-29.md",
    ]


def test_discovery_skips_a_symlinked_or_directory_user_md(tmp_path: Path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "user.md").write_text("u\n", encoding="utf-8")
    try:
        (tmp_path / "USER.md").symlink_to(tmp_path / "notes" / "user.md")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not supported on this platform: {exc}")
    assert MemoryWorkspace(tmp_path).discover_memory_files() == []

    (tmp_path / "USER.md").unlink()
    (tmp_path / "USER.md").mkdir()
    (tmp_path / "USER.md" / "inner.md").write_text("inner\n", encoding="utf-8")
    assert MemoryWorkspace(tmp_path).discover_memory_files() == []


def test_discovery_finds_a_lowercase_user_md_only_on_a_case_insensitive_file_system(
    tmp_path: Path,
):
    # Upstream lstats path.join(workspaceDir, "USER.md"); the file system decides.
    (tmp_path / "user.md").write_text("u\n", encoding="utf-8")
    case_insensitive = (tmp_path / "USER.md").exists()

    assert [entry.rel_path for entry in MemoryWorkspace(tmp_path).discover_memory_files()] == (
        ["USER.md"] if case_insensitive else []
    )


def test_discovery_sorts_the_memory_walk_by_path(tmp_path: Path):
    # internal.ts:246 sorts the collected paths (UTF-16 code units): "a-b.md" < "a.md" < "a/b.md"
    # ('-' 0x2D < '.' 0x2E < '/' 0x2F); a pre-order walk would list memory/a/b.md first. A
    # supplementary-plane name sorts before U+FF5E in UTF-16 (surrogates are 0xD800-0xDFFF).
    for relative in ("a.md", "a/b.md", "a-b.md", "\uff5e.md", "\U0001f600.md"):
        path = tmp_path / "memory" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")

    assert [entry.rel_path for entry in MemoryWorkspace(tmp_path).discover_memory_files()] == [
        "memory/a-b.md",
        "memory/a.md",
        "memory/a/b.md",
        "memory/\U0001f600.md",
        "memory/\uff5e.md",
    ]


def test_discovery_walks_dot_directories_but_not_repair_directories(tmp_path: Path):
    (tmp_path / "memory" / ".dreams").mkdir(parents=True)
    (tmp_path / "memory" / ".openclaw-repair").mkdir()
    (tmp_path / "memory" / ".dreams" / "diary.md").write_text("dot dir\n", encoding="utf-8")
    (tmp_path / "memory" / ".dreams" / "state.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "memory" / ".openclaw-repair" / "copy.md").write_text("skip\n", encoding="utf-8")

    workspace = MemoryWorkspace(tmp_path)

    assert [entry.rel_path for entry in workspace.discover_memory_files()] == [
        "memory/.dreams/diary.md"
    ]


def test_discovery_never_indexes_legacy_lowercase_root_memory(tmp_path: Path):
    (tmp_path / "memory.md").write_text("legacy\n", encoding="utf-8")

    assert MemoryWorkspace(tmp_path).discover_memory_files() == []


def test_discovery_skips_symlinked_files_and_directories(tmp_path: Path):
    (tmp_path / "memory" / "real").mkdir(parents=True)
    (tmp_path / "memory" / "real" / "note.md").write_text("real\n", encoding="utf-8")
    try:
        (tmp_path / "memory" / "alias.md").symlink_to(tmp_path / "memory" / "real" / "note.md")
        (tmp_path / "memory" / "aliasdir").symlink_to(tmp_path / "memory" / "real")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not supported on this platform: {exc}")

    assert [entry.rel_path for entry in MemoryWorkspace(tmp_path).discover_memory_files()] == [
        "memory/real/note.md"
    ]


def test_indexable_files_index_session_corpus_markdown_once_as_sessions(tmp_path: Path):
    corpus_dir = tmp_path / "memory" / ".dreams" / "session-corpus"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "2026-05-03.md").write_text("User: hello\n", encoding="utf-8")
    (tmp_path / "memory" / "2026-05-03.md").write_text("# Day\n", encoding="utf-8")

    files = MemoryWorkspace(tmp_path).discover_indexable_files()

    assert [(file.rel_path, file.source) for file in files] == [
        ("memory/2026-05-03.md", "memory"),
        ("memory/.dreams/session-corpus/2026-05-03.md", "sessions"),
    ]


def test_discovery_skips_dated_symlink_that_escapes_workspace(tmp_path: Path):
    outside_file = tmp_path.parent / "outside-memory.md"
    outside_file.write_text("# Outside\n", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    symlink_path = tmp_path / "memory" / "2026-05-04.md"
    try:
        symlink_path.symlink_to(outside_file)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not supported on this platform: {exc}")

    workspace = MemoryWorkspace(tmp_path)

    assert "memory/2026-05-04.md" not in [
        entry.rel_path for entry in workspace.discover_memory_files()
    ]


def test_discovers_openclaw_state_session_transcripts(tmp_path: Path):
    sessions_dir = tmp_path / ".openclaw-state" / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "session-nebula.jsonl").write_text(
        '{"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"ORBIT-10"}]}}\n',
        encoding="utf-8",
    )
    (sessions_dir / "sessions.json").write_text(
        '{"agent:main:session-nebula":{"sessionFile":"session-nebula.jsonl"}}\n',
        encoding="utf-8",
    )
    workspace = MemoryWorkspace(tmp_path, openclaw_state_dir=tmp_path / ".openclaw-state")

    files = workspace.discover_session_transcript_files()

    assert [(item.rel_path, item.source) for item in files] == [
        ("sessions/main/session-nebula.jsonl", "sessions")
    ]


def test_safe_read_rejects_parent_escape(tmp_path: Path):
    workspace = MemoryWorkspace(tmp_path)
    with pytest.raises(UnsafeMemoryPathError):
        workspace.read_text("../secret.txt")


def test_safe_read_rejects_non_memory_workspace_file(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("not memory\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    with pytest.raises(UnsafeMemoryPathError):
        workspace.read_text("notes.txt")


def test_safe_read_allows_dreams_file(tmp_path: Path):
    (tmp_path / "DREAMS.md").write_text("dream log\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    result = workspace.read_text("DREAMS.md")

    assert result.path == "DREAMS.md"
    assert result.text == "dream log\n"


def test_read_lines_uses_one_based_line_window(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("a\nb\nc\nd\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    result = workspace.read_text("MEMORY.md", from_line=2, line_count=2)

    assert result.path == "MEMORY.md"
    assert result.text == "b\nc\n"
    assert result.start_line == 2
    assert result.end_line == 3


def test_read_text_normalizes_returned_path(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("a\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    result = workspace.read_text("/MEMORY.md")

    assert result.path == "MEMORY.md"


def test_append_daily_memory_creates_memory_directory(tmp_path: Path):
    workspace = MemoryWorkspace(tmp_path)

    path = workspace.append_daily_memory("memory/2026-05-03.md", "- User prefers concise answers.")

    assert path.relative_to(tmp_path).as_posix() == "memory/2026-05-03.md"
    assert (tmp_path / "memory" / "2026-05-03.md").read_text(encoding="utf-8") == (
        "- User prefers concise answers.\n"
    )


def test_append_daily_memory_appends_without_overwriting(tmp_path: Path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    daily = memory_dir / "2026-05-03.md"
    daily.write_text("# 2026-05-03\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    workspace.append_daily_memory("memory/2026-05-03.md", "- Keep OpenClaw parity.")

    assert daily.read_text(encoding="utf-8") == "# 2026-05-03\n- Keep OpenClaw parity.\n"


def test_append_daily_memory_separates_existing_content_without_trailing_newline(
    tmp_path: Path,
):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    daily = memory_dir / "2026-05-03.md"
    daily.write_text("# 2026-05-03", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    workspace.append_daily_memory("memory/2026-05-03.md", "- Keep OpenClaw parity.")

    assert daily.read_text(encoding="utf-8") == "# 2026-05-03\n- Keep OpenClaw parity.\n"


def test_append_daily_memory_rejects_symlink_target(tmp_path: Path):
    bootstrap = tmp_path / "MEMORY.md"
    bootstrap.write_text("# Protected\n", encoding="utf-8")
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    daily = memory_dir / "2026-05-03.md"
    try:
        daily.symlink_to(bootstrap)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not supported on this platform: {exc}")
    workspace = MemoryWorkspace(tmp_path)

    with pytest.raises(UnsafeMemoryPathError):
        workspace.append_daily_memory("memory/2026-05-03.md", "- bad")

    assert bootstrap.read_text(encoding="utf-8") == "# Protected\n"


def test_append_daily_memory_rejects_bootstrap_and_timestamped_files(tmp_path: Path):
    workspace = MemoryWorkspace(tmp_path)

    with pytest.raises(UnsafeMemoryPathError):
        workspace.append_daily_memory("MEMORY.md", "- bad")
    with pytest.raises(UnsafeMemoryPathError):
        workspace.append_daily_memory("memory/2026-05-03-1200.md", "- bad")


def test_append_daily_memory_rejects_non_canonical_paths(tmp_path: Path):
    workspace = MemoryWorkspace(tmp_path)

    with pytest.raises(UnsafeMemoryPathError):
        workspace.append_daily_memory("/memory/2026-05-03.md", "- bad")
    with pytest.raises(UnsafeMemoryPathError):
        workspace.append_daily_memory(r"memory\2026-05-03.md", "- bad")
