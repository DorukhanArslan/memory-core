from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DATED_MEMORY_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
DAILY_MEMORY_PATH_RE = re.compile(r"^memory/\d{4}-\d{2}-\d{2}\.md$")
SESSION_CORPUS_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.(?:md|txt)$")


class UnsafeMemoryPathError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryFile:
    rel_path: str
    abs_path: Path
    source: str = "memory"


@dataclass(frozen=True)
class MemoryReadResult:
    path: str
    text: str
    start_line: int
    end_line: int


class MemoryWorkspace:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def discover_memory_files(self) -> list[MemoryFile]:
        files: list[MemoryFile] = []
        for name in ("MEMORY.md", "memory.md"):
            path = self.root / name
            resolved_path = path.resolve()
            if path.is_file() and self.is_path_inside_root(resolved_path):
                files.append(MemoryFile(name, resolved_path))
                break
        memory_dir = self.root / "memory"
        if memory_dir.is_dir():
            for path in sorted(memory_dir.glob("*.md")):
                resolved_path = path.resolve()
                if DATED_MEMORY_FILE_RE.match(path.name) and self.is_path_inside_root(
                    resolved_path
                ):
                    files.append(MemoryFile(path.relative_to(self.root).as_posix(), resolved_path))
        return files

    def discover_session_transcript_files(self) -> list[MemoryFile]:
        files: list[MemoryFile] = []
        session_dir = self.root / "memory" / ".dreams" / "session-corpus"
        if session_dir.is_dir():
            for path in sorted(session_dir.iterdir()):
                resolved_path = path.resolve()
                if SESSION_CORPUS_FILE_RE.match(path.name) and self.is_path_inside_root(
                    resolved_path
                ):
                    files.append(
                        MemoryFile(
                            path.relative_to(self.root).as_posix(),
                            resolved_path,
                            source="sessions",
                        )
                    )
        return files

    def discover_indexable_files(self) -> list[MemoryFile]:
        return [*self.discover_memory_files(), *self.discover_session_transcript_files()]

    def normalize_memory_path(self, rel_path: str) -> str:
        return rel_path.replace("\\", "/").lstrip("/")

    def is_allowed_memory_path(self, rel_path: str) -> bool:
        normalized = self.normalize_memory_path(rel_path)
        if normalized in {"MEMORY.md", "memory.md", "DREAMS.md"}:
            return True
        if not normalized.startswith("memory/"):
            return False
        return normalized.endswith(".md")

    def is_path_inside_root(self, path: Path) -> bool:
        return path == self.root or self.root in path.parents

    def resolve_memory_path(self, rel_path: str) -> Path:
        normalized = self.normalize_memory_path(rel_path)
        if not self.is_allowed_memory_path(normalized):
            raise UnsafeMemoryPathError(f"path is not an allowed memory file: {rel_path}")
        candidate = (self.root / normalized).resolve()
        if not self.is_path_inside_root(candidate):
            raise UnsafeMemoryPathError(f"memory path escapes workspace: {rel_path}")
        return candidate

    def append_daily_memory(self, rel_path: str, entry: str) -> Path:
        if DAILY_MEMORY_PATH_RE.match(rel_path) is None:
            raise UnsafeMemoryPathError(f"path is not a canonical daily memory file: {rel_path}")
        lexical_path = self.root / rel_path
        if lexical_path.is_symlink():
            raise UnsafeMemoryPathError(f"memory path is a symlink: {rel_path}")
        path = lexical_path.resolve()
        if not self.is_path_inside_root(path):
            raise UnsafeMemoryPathError(f"memory path escapes workspace: {rel_path}")

        path.parent.mkdir(parents=True, exist_ok=True)
        if entry.strip():
            text = entry.rstrip("\r\n")
            needs_separator = False
            if path.exists() and path.stat().st_size > 0:
                with path.open("rb") as existing:
                    existing.seek(-1, 2)
                    needs_separator = existing.read(1) != b"\n"
            with path.open("a", encoding="utf-8") as handle:
                if needs_separator:
                    handle.write("\n")
                handle.write(f"{text}\n")
        return path

    def read_text(
        self,
        rel_path: str,
        *,
        from_line: int | None = None,
        line_count: int | None = None,
    ) -> MemoryReadResult:
        path = self.resolve_memory_path(rel_path)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        start = max(1, from_line or 1)
        if line_count is None:
            selected = lines[start - 1 :]
        else:
            selected = lines[start - 1 : start - 1 + max(0, line_count)]
        end = start + len(selected) - 1 if selected else start - 1
        return MemoryReadResult(self.normalize_memory_path(rel_path), "".join(selected), start, end)
