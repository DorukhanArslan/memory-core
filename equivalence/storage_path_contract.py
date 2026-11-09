"""Dedicated whole-tool path admission inputs for fixed storage contract #2.

Only private fixture inputs are declared here. The authenticated public
memory_get factory and real filesystem owners determine every outcome. These
cases receive no acceptance credit before paired capture and independent review.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


_PROFILE = (
    "Complete provider-none memory_get factory/execute and actual secure filesystem "
    "read owners over private Linux files, directories, symlinks and hardlinks. "
    "Absolute, relative, traversal and encoded requests reach "
    "the genuine public tool without URL decoding or lexical path repair. Trusted "
    "plain and patterned extra roots are host configuration, never model authority. "
    "Both owned workspace and outside trees are observed before and after all reads. "
    "Every result, rejection and actual OS error remains visible, including existing "
    "ELOOP and patterned-root SDK gaps. This profile claims no filesystem races, "
    "descriptor replacement, retry timing, deadlines, writes, provider execution, "
    "session-history visibility or general cross-platform path semantics."
)
_POLICY = (
    "Complete ordered tool envelopes and read results without field projection, "
    "truncation repair, sorting or tolerance. The reviewed JSON carrier codec "
    "verifies each text carrier parses exactly to details and retains every "
    "content/envelope field; untouched wire strings remain in raw diagnostics. "
    "Private $WORKSPACE and $OUTSIDE input prefixes expand only to their owned "
    "fixture roots, preserving every request suffix, including traversal. After "
    "complete envelope validation, only the exact owned private fixture-base "
    "prefix maps to $FIXTURE in JSON string values. Error wording, codes, causes, "
    "path suffixes, field absence and operation order remain intact. Complete "
    "before/after filesystem observations cover both owned roots without "
    "following symlinks or reading special files. All raw stat properties and complete "
    "file bytes remain attested; the public snapshot codec compares content, file type, "
    "POSIX mode/uid/gid/nlink/rdev, actual hardlink relations and exact within-side "
    "write-stat stability. Raw access times may change through reads. No changed file is repaired."
)


def build_storage_path_contract_cases() -> list[dict[str, Any]]:
    """Return independent real-input batches under the existing get capability."""
    cases: list[dict[str, Any]] = []

    def add(name: str, requests: list[str | dict[str, Any]], **fixtures: Any) -> None:
        cases.append({
            "id": f"storage-path-contract-{name}",
            "requirement": "storage.path-safety",
            "covers": [],
            "operation": "get-contract-runtime",
            "driverScope": _PROFILE,
            "normalizationPolicy": _POLICY,
            "input": {
                "kind": "tool",
                "normalizeFixturePaths": True,
                "observeFilesystem": True,
                **deepcopy(fixtures),
                "steps": [{"params": {"path": request} if isinstance(request, str)
                           else deepcopy(request)} for request in requests],
            },
        })

    ordinary_files = {
        "MEMORY.md": "Canonical root memory.\n",
        "USER.md": "User memory.\n",
        "DREAMS.md": "Dream memory.\n",
        "dreams.md": "Lowercase dream memory.\n",
        "memory.md": "Legacy lowercase root.\n",
        "AGENTS.md": "Private agent instructions.\n",
        "memory/note.md": "Nested durable memory.\n",
        "memory/UPPER.MD": "Uppercase extension.\n",
        "memory/note.txt": "Non-Markdown bytes.\n",
    }
    add("root-relative-and-absolute", [
        "MEMORY.md", "./MEMORY.md", "$WORKSPACE/MEMORY.md",
        "USER.md", "DREAMS.md", "dreams.md", "memory.md", "AGENTS.md",
        "memory/note.md", "$WORKSPACE/memory/note.md", "memory/UPPER.MD",
        "memory/note.txt", "\ufeff memory/note.md\u00a0", "", " \t", ".", "memory/",
    ], files=ordinary_files)

    add("traversal-and-missing", [
        "$OUTSIDE/secret.md", "../outside/secret.md", "memory/../../outside/secret.md",
        "$WORKSPACE/../outside/secret.md", "$WORKSPACE/memory/../../outside/secret.md",
        "memory/../MEMORY.md", "memory/../AGENTS.md", "memory/./note.md",
        "memory/sub/../note.md", "memory//note.md", "MEMORY.md/../MEMORY.md",
        "memory/missing.md", "memory/missing/child.md", "memory/note.md/child.md",
        "sessions/main/one.jsonl", "memory/.dreams/session-corpus/one.txt",
        {"path": "../outside/secret.md", "extraPaths": ["$OUTSIDE"]},
    ], files=ordinary_files, outsideFiles={"secret.md": "Outside secret stays private.\n"})

    add("encoded-literals-and-raw-boundaries", [
        "memory/%6eote.md", "memory/note.md", "memory/%2e%2e/AGENTS.md",
        "memory/%252e%252e/AGENTS.md", "memory/%2f../AGENTS.md",
        "memory/%2Fsecret.md", "memory/a%00.md", "memory/a%20b.md",
        "memory/a b.md", "memory\\note.md", "MEMORY.md\x00.md",
        "memory/%2e%2e/../../../outside/secret.md", "$WORKSPACE/memory/%6eote.md",
    ], files={
        "MEMORY.md": "Canonical root.\n",
        "memory/note.md": "Unencoded name.\n",
        "memory/%6eote.md": "Literal encoded-looking name.\n",
        "memory/%2e%2e/AGENTS.md": "Literal percent directory.\n",
        "memory/%252e%252e/AGENTS.md": "Literal double-percent directory.\n",
        "memory/%2f../AGENTS.md": "Literal slash-looking directory.\n",
        "memory/%2Fsecret.md": "Literal slash-looking leaf.\n",
        "memory/a%00.md": "Literal zero-looking name.\n",
        "memory/a%20b.md": "Literal space-looking name.\n",
        "memory/a b.md": "Actual space name.\n",
    }, outsideFiles={"secret.md": "Outside encoded-path sentinel.\n"})

    add("symlink-admission", [
        "memory/leaf.md", "memory/external-leaf.md", "memory/broken.md",
        "memory/inside/note.md", "memory/inside-chain/note.md",
        "memory/outside/secret.md", "memory/outside/missing.md",
        "memory/outside-chain/secret.md", "memory/broken-parent/note.md",
        "memory/file-parent/note.md", "memory/leaf-loop.md",
        "$WORKSPACE/memory/inside/note.md", "$WORKSPACE/memory/outside/secret.md",
    ], files={"memory/real/note.md": "Inside-root parent symlink content.\n"},
        outsideFiles={"secret.md": "Outside symlink sentinel.\n"}, symlinks={
            "memory/leaf.md": {"scope": "workspace", "path": "memory/real/note.md"},
            "memory/external-leaf.md": {"scope": "outside", "path": "secret.md"},
            "memory/broken.md": {"scope": "workspace", "path": "memory/absent.md"},
            "memory/inside": {"scope": "workspace", "path": "memory/real"},
            "memory/inside-chain": {"scope": "workspace", "path": "memory/inside"},
            "memory/outside": {"scope": "outside", "path": "."},
            "memory/outside-chain": {"scope": "workspace", "path": "memory/outside"},
            "memory/broken-parent": {"scope": "workspace", "path": "memory/absent"},
            "memory/file-parent": {"scope": "workspace", "path": "memory/real/note.md"},
            "memory/leaf-loop.md": {"scope": "workspace", "path": "memory/leaf-loop.md"},
        })

    add("symlink-loop-os-errors", ["memory/loop/note.md", "memory/pair-a/note.md"], files={}, symlinks={
        "memory/loop": {"scope": "workspace", "path": "memory/loop"},
        "memory/pair-a": {"scope": "workspace", "path": "memory/pair-b"},
        "memory/pair-b": {"scope": "workspace", "path": "memory/pair-a"},
    })

    add("nonregular-and-hardlinks", [
        "memory/directory.md",
        "memory/inside-hardlink.md", "memory/outside-hardlink.md",
        "$WORKSPACE/memory/outside-hardlink.md",
    ], files={"memory/real.md": "Inside hardlink content.\n"},
        outsideFiles={"secret.md": "Outside hardlink content, intentionally aliased.\n"},
        directories=["memory/directory.md"], hardlinks={
            "memory/inside-hardlink.md": {"scope": "workspace", "path": "memory/real.md"},
            "memory/outside-hardlink.md": {"scope": "outside", "path": "secret.md"},
        })

    for name, workspace_kind in (("missing-workspace", "missing"), ("workspace-is-file", "file")):
        add(name, ["MEMORY.md", "$WORKSPACE/MEMORY.md", "memory/missing.md", "$OUTSIDE/secret.md"],
            workspaceKind=workspace_kind, outsideFiles={"secret.md": "Outside root sentinel.\n"})

    add("plain-extra-root-authority", [
        "notes/a.md", "notes/nested/b.md", "named.md", "AGENTS.md", "notes/a.txt",
        "notes/UPPER.MD", "notes/missing.md", "notes/leaf-link.md", "notes/inside/a.md",
        "linked-root/a.md", "notes/directory.md", "notes/not-dir/a.md",
        "$OUTSIDE/secret.md", "../outside/secret.md", "notes/../../outside/secret.md",
        {"path": "unconfigured/private.md", "extraPaths": ["unconfigured"]},
    ], files={
        "notes/a.md": "Configured directory content.\n",
        "notes/nested/b.md": "Configured nested directory content.\n",
        "notes/a.txt": "Configured directory non-Markdown.\n",
        "notes/UPPER.MD": "Configured directory uppercase extension.\n",
        "notes/not-dir": "Not a directory.\n",
        "named.md": "Explicit configured file.\n",
        "AGENTS.md": "Explicitly configured agent file.\n",
        "unconfigured/private.md": "Unconfigured sibling stays private.\n",
    }, outsideFiles={"secret.md": "Host-authorized private outside root.\n"},
        directories=["notes/directory.md"], symlinks={
            "notes/leaf-link.md": {"scope": "workspace", "path": "notes/a.md"},
            "notes/inside": {"scope": "workspace", "path": "notes"},
            "linked-root": {"scope": "workspace", "path": "notes"},
        }, config={"extraPaths": ["notes", "named.md", "AGENTS.md", "linked-root", "$OUTSIDE"]})

    add("patterned-extra-root-admission", [
        "notes/public/a.md", "notes/public/nested/b.md", "notes/shared/c.md",
        "notes/private/secret.md", "notes/public/a.txt", "notes/public/missing.md",
        "named.md", "$OUTSIDE/secret.md",
    ], files={
        "notes/public/a.md": "Allowed public path.\n",
        "notes/public/nested/b.md": "Allowed nested public path.\n",
        "notes/shared/c.md": "Allowed by the second same-root pattern.\n",
        "notes/private/secret.md": "Excluded by both trusted patterns.\n",
        "notes/public/a.txt": "Non-Markdown even under a matched pattern.\n",
        "named.md": "Explicit file admission retains the native policy.\n",
    }, outsideFiles={"secret.md": "Outside patterned-root sentinel.\n"}, config={"extraPaths": [
        {"path": "notes", "pattern": "public/**/*.md"},
        {"path": "notes", "pattern": "shared/*.md"},
        {"path": "named.md", "pattern": "excluded/**"},
    ]})
    return cases
