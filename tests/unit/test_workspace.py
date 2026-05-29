from pathlib import Path

import pytest

from memory_core.workspace import MemoryWorkspace, UnsafeMemoryPathError


def test_discovers_root_and_dated_memory_files(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("# Long\n", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-05-03.md").write_text("# Day\n", encoding="utf-8")
    (tmp_path / "memory" / "abcd-ef-gh.md").write_text("skip\n", encoding="utf-8")
    (tmp_path / "memory" / "notes.txt").write_text("skip\n", encoding="utf-8")

    workspace = MemoryWorkspace(tmp_path)

    assert [entry.rel_path for entry in workspace.discover_memory_files()] == [
        "MEMORY.md",
        "memory/2026-05-03.md",
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
