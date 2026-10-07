"""Oracle test of the memory-write provenance observer against OpenClaw v2026.9.6.

One real-TS run (``memoryWriteProvenance``: ``createMemoryWriteProvenanceObserver`` of
``src/agents/memory-write-provenance.ts`` over the real trust store), replayed step by step in Python
(``memory_core.memory_write_provenance``). After every step the trust records of the workspace (hash,
origin class, time, session) and the classification answers must agree: trusted chains, a sticky
untrusted record, an edit between two writes, rolled-back writes, deleted files, symlink aliases that
stay inside the memory root, symlinks and paths that leave it, and files the store does not track.
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver


def _write(path: str, before: str, after: str, klass: str = "agent", at: int = 1000, **over: Any) -> dict[str, Any]:
    return {
        "kind": "write",
        "path": path,
        "contentBefore": before,
        "contentAfter": after,
        "originClass": klass,
        "observedAt": at,
        **over,
    }


def _scenarios() -> dict[str, list[dict[str, Any]]]:
    daily = "memory/2026-05-26.md"
    scenarios: dict[str, list[dict[str, Any]]] = {
        "trusted_chain": [
            _write(daily, "", "a1\n", at=1),
            _write(daily, "a1\n", "a1\na2\n", at=2, sessionId="s1", sessionKey="agent:main:s1"),
            _write(daily, "a1\na2\n", "a1\na2\na3\n", at=3),
        ],
        "untrusted_is_sticky": [
            _write(daily, "", "u1\n", "untrusted", at=1),
            _write(daily, "u1\n", "u1\nt2\n", "agent", at=2),
            _write(daily, "u1\nt2\n", "u1\nt2\nt3\n", "agent", at=3),
        ],
        "edit_between_writes_downgrades": [
            _write(daily, "", "a1\n", at=1),
            _write(daily, "a1 edited by hand\n", "a1 edited by hand\na2\n", at=2),
            _write(daily, "x", "y", at=3),
        ],
        "first_write_with_content_before": [_write(daily, "old text\n", "old text\nnew\n")],
        "failed_commit_rolls_back_new_record": [
            _write(daily, "", "a1\n", at=1, failCommit=True),
            _write("MEMORY.md", "", "m1\n", at=2),
            _write("MEMORY.md", "m1\n", "m1\nm2\n", at=3, failCommit=True),
            _write("MEMORY.md", "m1\n", "m1\nm2\n", at=4),
        ],
        "classification": [
            *[
                {"kind": "classifies", "path": p}
                for p in [
                    "MEMORY.md",
                    "memory.md",
                    "USER.md",
                    "users/abc/USER.md",
                    "users/a b/USER.md",
                    "users/abc/other.md",
                    "memory/2026-05-26.md",
                    "memory/notes.md",
                    "memory/sub/deep.md",
                    "memory/image.png",
                    "memory/.dreams/short-term-recall.json",
                    "memory/dreaming/light/2026-05-26.md",
                    "notes.txt",
                    "src/main.py",
                    "../outside.md",
                    "../../memory/escape.md",
                    "memory",
                    "",
                ]
            ],
            _write("notes.txt", "", "n\n"),
            _write("memory/.dreams/x.md", "", "x\n"),
            _write("memory/dreaming/y.md", "", "y\n"),
            _write("users/abc/USER.md", "", "u\n"),
        ],
        "delete_clears_matching_record": [
            _write(daily, "", "a1\n", at=1),
            {"kind": "delete", "path": daily, "contentBefore": "something else\n"},
            _write(daily, "a1\n", "a1\nb\n", at=2),
            {"kind": "delete", "path": daily, "contentBefore": "a1\nb\n"},
            {"kind": "delete", "path": "memory/never-written.md", "contentBefore": ""},
        ],
        "symlink_alias_inside_the_root": [
            {"kind": "mkdir", "path": "memory"},
            {"kind": "symlink", "path": "alias", "target": "memory"},
            {"kind": "classifies", "path": "alias/2026-05-26.md"},
            _write("alias/2026-05-26.md", "", "via alias\n", "untrusted", at=1),
            _write(daily, "via alias\n", "via alias\ndirect\n", "agent", at=2),
        ],
        "symlink_leaving_the_root": [
            {"kind": "mkdir", "path": "../elsewhere-memory"},
            {"kind": "symlink", "path": "memory", "target": "../elsewhere-memory"},
            {"kind": "classifies", "path": "memory/2026-05-26.md"},
            _write("memory/2026-05-26.md", "", "outside\n", at=1),
        ],
        "dangling_symlink": [
            {"kind": "symlink", "path": "memory-link", "target": "missing-target"},
            {"kind": "classifies", "path": "memory-link/x.md"},
        ],
        "session_fields": [
            _write(daily, "", "a\n", at=1, sessionId="sid-1", sessionKey="agent:main:one"),
            _write("MEMORY.md", "", "b\n", at=2, sessionKey="only-key"),
            _write("USER.md", "", "c\n", at=3, sessionId="only-id"),
        ],
    }
    rng = random.Random(20261004)
    files = [daily, "memory/2026-05-25.md", "MEMORY.md", "USER.md", "memory/notes.md"]
    for index in range(20):
        content: dict[str, str] = {}
        steps: list[dict[str, Any]] = []
        for turn in range(rng.randint(3, 12)):
            path = rng.choice(files)
            before = content.get(path, "")
            if rng.random() < 0.15:
                before = before + "edited "
            after = before + f"line {turn}\n"
            fail = rng.random() < 0.15
            steps.append(
                _write(path, before, after, rng.choice(["agent", "agent", "untrusted"]), at=turn + 1, failCommit=fail)
            )
            if not fail:
                content[path] = after
            if rng.random() < 0.15:
                steps.append({"kind": "delete", "path": path, "contentBefore": content.get(path, "")})
                content.pop(path, None)
        scenarios[f"random_{index:02d}"] = steps
    return scenarios


@pytest.fixture(scope="module")
def _ts(tmp_path_factory):
    root = tmp_path_factory.mktemp("write-provenance-ts")
    payload = [
        {"name": name, "workspaceDir": str(root / name / "ws"), "steps": steps}
        for name, steps in _scenarios().items()
    ]
    response = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=600).run(
        {"operation": "memoryWriteProvenance", "provenanceScenarios": payload}
    )
    assert response["ok"] is True, response.get("error")
    return {item["name"]: item for item in response["result"]["scenarios"]}


def _records(store: MemoryArtifactProvenanceStore, workspace: Path) -> list[dict[str, Any]]:
    out = []
    for relative, record in store.list(workspace):
        provenance: dict[str, Any] = {
            "fileHash": record.file_hash,
            "originClass": record.origin_class,
            "observedAt": record.observed_at,
        }
        if record.session_id:
            provenance["sessionId"] = record.session_id
        if record.session_key:
            provenance["sessionKey"] = record.session_key
        out.append({"relativePath": relative, "provenance": provenance})
    return sorted(out, key=lambda item: item["relativePath"])


def _wanted(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda item: item["relativePath"])


@pytest.mark.parametrize("name", sorted(_scenarios()))
def test_write_provenance_matches_openclaw(name: str, _ts, tmp_path: Path) -> None:
    workspace = tmp_path / name / "ws"
    workspace.mkdir(parents=True)
    store = MemoryArtifactProvenanceStore(tmp_path / name / "provenance.sqlite")
    for index, (step, expected) in enumerate(zip(_scenarios()[name], _ts[name]["steps"], strict=True)):
        label = f"{name} step {index} ({step['kind']} {step['path']})"
        target = Path(step["path"]) if os.path.isabs(step["path"]) else workspace / step["path"]
        error: str | None = None
        result: Any = None
        try:
            if step["kind"] == "symlink":
                target.parent.mkdir(parents=True, exist_ok=True)
                link_target = Path(step["target"]) if os.path.isabs(step["target"]) else workspace / step["target"]
                os.symlink(link_target, target)
            elif step["kind"] == "mkdir":
                target.mkdir(parents=True, exist_ok=True)
            else:
                observer = MemoryWriteProvenanceObserver(
                    store=store,
                    mutation_root=workspace,
                    workspace_dir=workspace,
                    resolve_origin_class=lambda step=step: step.get("originClass", "agent"),
                    session_id=step.get("sessionId"),
                    session_key=step.get("sessionKey"),
                    now=lambda step=step: int(step.get("observedAt", 0)),
                )
                if step["kind"] == "classifies":
                    result = observer.classifies(target)
                elif step["kind"] == "write":
                    target.parent.mkdir(parents=True, exist_ok=True)

                    def commit(step: dict[str, Any] = step, target: Path = target) -> None:
                        if step.get("failCommit"):
                            raise RuntimeError("commit failed")
                        target.write_text(step.get("contentAfter", ""), "utf-8")

                    observer.write(
                        absolute_path=target,
                        content_before=step.get("contentBefore", ""),
                        content_after=step.get("contentAfter", ""),
                        commit=commit,
                    )
                elif step["kind"] == "delete":
                    target.unlink(missing_ok=True)
                    observer.clear_after_delete(target, step.get("contentBefore", ""))
        except Exception as caught:
            error = str(caught)
        assert error == expected["error"], label
        assert result == expected["result"], label
        assert _records(store, workspace) == _wanted(expected["records"]), label


def test_scenarios_cover_trust_and_rollback(_ts) -> None:
    def classes(name: str) -> list[list[str]]:
        return [[r["provenance"]["originClass"] for r in s["records"]] for s in _ts[name]["steps"]]

    assert classes("trusted_chain")[-1] == ["agent"]
    assert classes("untrusted_is_sticky")[-1] == ["untrusted"]
    assert classes("edit_between_writes_downgrades")[1] == ["untrusted"]
    rollback = _ts["failed_commit_rolls_back_new_record"]["steps"]
    assert rollback[0]["error"] == "commit failed" and rollback[0]["records"] == []
    answers = [s["result"] for s in _ts["classification"]["steps"] if s["result"] is not None]
    assert True in answers and False in answers
    assert _ts["symlink_leaving_the_root"]["steps"][2]["result"] is False
    assert _ts["symlink_alias_inside_the_root"]["steps"][2]["result"] is True
