"""Inspect and archive the session corpus without losing its original files."""
from __future__ import annotations

import errno
from pathlib import Path
import stat
from uuid import uuid4

from memory_core.consolidation._util import iso_ms
from memory_core.consolidation.session_ingestion import SESSION_CORPUS_RELATIVE_DIR, SESSION_INGESTION_STATE_RELATIVE_PATH


def _directory(workspace: Path) -> Path:
    if not workspace.is_absolute():
        raise ValueError("workspaceDir must be an absolute path")
    return workspace.resolve()


def _artifact(workspace: Path, name: str | Path) -> Path:
    candidate = workspace / name
    if candidate.parent.resolve() != candidate.parent:
        raise ValueError(f"Refusing to use symlinked artifact directory: {candidate.parent}")
    return candidate


def _diary(workspace: Path) -> Path | None:
    return next((workspace / name for name in ("DREAMS.md", "dreams.md") if (workspace / name).exists()), None)


def audit_dreaming_artifacts(workspace: Path) -> dict:
    """Count contaminated session-corpus lines and report the original artifact locations."""
    workspace = _directory(workspace)
    corpus = _artifact(workspace, SESSION_CORPUS_RELATIVE_DIR)
    ingestion = _artifact(workspace, SESSION_INGESTION_STATE_RELATIVE_PATH)
    diary = _diary(workspace)
    issues = []
    counts = []
    files = []
    try:
        if corpus.is_symlink():
            raise ValueError(f"Refusing to inspect symlinked path: {corpus}")
        files = sorted(p for p in corpus.iterdir() if not p.is_symlink() and p.is_file() and p.suffix == ".txt")
        for file in files:
            counts.append(sum("Write a dream diary entry from these memory fragments" in line
                              and "dreaming-narrative-" in line
                              for line in file.read_bytes().decode("utf-8", "replace").splitlines()))
    except FileNotFoundError:
        pass
    except OSError as exc:
        code = errno.errorcode.get(exc.errno, "error")
        issues.append({"severity": "error", "code": "dreaming-session-corpus-unreadable",
                       "message": f"Dreaming session corpus could not be inspected: {code}.", "fixable": False})
    total = sum(counts)
    if total:
        issues.append({"severity": "warn", "code": "dreaming-session-corpus-self-ingested",
                       "message": f"Dreaming session corpus appears to contain self-ingested narrative "
                                  f"content ({total} suspicious line{'s' if total != 1 else ''}).", "fixable": True})
    return {**({"dreamsPath": str(diary)} if diary else {}), "sessionCorpusDir": str(corpus),
            "sessionCorpusFileCount": len(files), "suspiciousSessionCorpusFileCount": sum(n > 0 for n in counts),
            "suspiciousSessionCorpusLineCount": total, "sessionIngestionPath": str(ingestion),
            "sessionIngestionExists": ingestion.exists(), "issues": issues}


def repair_dreaming_artifacts(workspace: Path, *, now_ms: int, archive_diary: bool = False) -> dict:
    """Move complete artifacts to collision-resistant archive paths and return actual receipts."""
    workspace = _directory(workspace)
    archive = _artifact(workspace, Path(".openclaw-repair/dreaming") / iso_ms(now_ms).replace(":", "-").replace(".", "-"))
    archived, warnings = [], []
    def move(target: Path) -> bool:
        try:
            target = _artifact(workspace, target.relative_to(workspace))
            mode = target.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError(f"Refusing to archive symlinked path: {target}")
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError(f"Refusing to archive non-file artifact: {target}")
            if archive.is_symlink():
                raise ValueError(f"Refusing to use symlinked archive directory: {archive}")
            archive.mkdir(parents=True, exist_ok=True)
            destination = archive / f"{target.name}.{uuid4()}"
            target.rename(destination)
            archived.append(str(destination))
            return True
        except FileNotFoundError:
            return False
        except (ValueError, OSError) as exc:
            warnings.append(str(exc))
            return False
    corpus = move(workspace / SESSION_CORPUS_RELATIVE_DIR)
    ingestion = move(workspace / SESSION_INGESTION_STATE_RELATIVE_PATH)
    diary = _diary(workspace) if archive_diary else None
    did_diary = move(diary) if diary else False
    return {"changed": bool(archived), "archiveDir": str(archive), "archivedDreamsDiary": did_diary,
            "archivedSessionCorpus": corpus, "archivedSessionIngestion": ingestion,
            "archivedPaths": archived, "warnings": warnings}
