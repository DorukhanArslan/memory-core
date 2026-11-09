"""Literal, initially uncredited atomic publication comparison fixtures."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any


_DAY = "memory/2026-09-04.md"
_INITIAL = "# Memory\n\n- original\n"
_REPLACEMENT = "# Memory\n\n- replacement\n"
_OPERATIONS = {"commit": "atomic-commit-runtime", "append": "atomic-append-runtime",
               "bootstrap": "atomic-bootstrap-runtime"}
_SCOPE = (
    "Genuine checked memory-content publication, Root.append, or exclusive bootstrap publisher; "
    "no provider, index, manager, worker, scheduler, or full agent-tool execution claim. "
    "Literal faults wrap delegated IO and preserve actual outcomes, full errors and surviving files."
)
_POLICY = (
    "Complete outcomes and error fields are retained, including errno/syscall, recursive causes, "
    "aggregate and suppressed errors, categories and publication receipts. Only the exact owned "
    "root, independently bound exclusive attempts/stages and lossless integer representations may "
    "use the declared atomic receipt codec. Unbound physical values remain ordinary differences."
)


def _fault(identity, operation, role, effect="reject-before", code="EIO", message=None, **facts):
    return {"id": identity, "operation": operation, "role": role, "effect": effect,
            "occurrence": 1, "code": code, "message": message or f"literal {identity}", **facts}


def _case(name, kind="commit", *, initial=_INITIAL, content=_REPLACEMENT, mode=0o640,
          parent_mode=0o755, faults=(), concurrency=None):
    path = "MEMORY.md" if kind == "commit" else "AGENTS.md" if kind == "bootstrap" else _DAY
    request = {"content": content, "expectedContent": (initial or "") if kind == "commit" else None,
               "expectedHash": hashlib.sha256((initial or "").encode("utf-8")).hexdigest() if kind == "commit" else None,
               "allowInPlaceFallback": False, "prependNewlineIfNeeded": kind == "append",
               "tempPrefix": ".MEMORY.atomic-proof"}
    value = {"kind": kind, "version": 1, "path": path,
             "initial": None if initial is None else {"content": initial, "mode": mode},
             "parentMode": parent_mode, "umask": 0o022, "request": request, "faults": list(faults)}
    if concurrency is not None:
        value["concurrency"] = concurrency
    return {"id": f"storage.atomic-writes.{name}", "requirement": "storage.atomic-writes",
            "operation": _OPERATIONS[kind], "input": value, "covers": [],
            "driverScope": _SCOPE, "normalizationPolicy": _POLICY}


def build_atomic_publication_cases() -> list[dict[str, Any]]:
    """Return the original 32 intents and nine declared settlement boundaries."""
    cases = [
        _case("ordinary-replace"),
        _case("temp-file-fsync-eperm", faults=[_fault("temp-sync-eperm", "file-sync", "stage", code="EPERM", message="literal fsync refusal")]),
        _case("temp-file-fsync-eio", faults=[_fault("temp-sync-eio", "file-sync", "stage", message="literal sync failure")]),
        _case("parent-directory-fsync-eio", faults=[_fault("parent-sync-eio", "parent-sync", "parent", message="literal directory sync failure")]),
        _case("rename-rejected-before-mutation", faults=[_fault("rename-before", "publish", "target", code="EACCES", message="literal rename refusal")]),
        _case("rename-mutates-then-rejects", faults=[_fault("rename-after", "publish", "target", "reject-after", message="literal dispatched rename failure")]),
        _case("published-target-external-inplace-edit", faults=[_fault("external-inplace", "publish", "target", "external-inplace", code=None,
                                                                      externalContent="# External edit\n")]),
        _case("published-target-rename-replacement", faults=[_fault("external-replace", "publish", "target", "external-replace", code=None,
                                                                     externalContent="# External replacement\n")]),
    ]
    for name, mode, faults in [
        ("promotion-readonly-directory-fallback", 0o640, []),
        ("promotion-readonly-target-rejects", 0o440, []),
        ("promotion-partial-write-restores-original", 0o640,
         [_fault("fallback-write-partial", "write", "target", "partial-write", code="EFBIG", message="literal in-place write failure", bytes=5)]),
        ("promotion-file-sync-restores-original", 0o640,
         [_fault("fallback-sync", "file-sync", "target", message="literal in-place sync failure")]),
    ]:
        case = _case(name, mode=mode, parent_mode=0o555, faults=faults)
        case["input"]["request"]["allowInPlaceFallback"] = True
        cases.append(case)
    cases.extend([
        _case("bootstrap-missing", "bootstrap", initial=None, content="complete bootstrap data\n"),
        _case("bootstrap-existing", "bootstrap", initial="original\n", content="new\n"),
        _case("bootstrap-partial-efbig", "bootstrap", initial=None, content="complete bootstrap data\n", faults=[
            _fault("bootstrap-efbig", "write", "stage", "partial-write", code="EFBIG", message="EFBIG: file too large, write", bytes=8),
        ]),
        _case("append-existing-newline", "append", initial="original\n", content="new\n"),
        _case("append-existing-without-newline", "append", initial="original", content="new\n"),
        _case("append-leading-newline", "append", initial="original", content="\nnew\n"),
        _case("append-missing", "append", initial=None, content="new\n"),
        _case("append-partial-efbig", "append", initial="before\n", content="new complete append data\n", faults=[
            _fault("append-efbig", "write", "target", "partial-write", code="EFBIG", message="EFBIG: file too large, write", bytes=1),
        ]),
    ])
    for kind in ("bootstrap", "append"):
        role = "stage" if kind == "bootstrap" else "target"
        for operation, code, effect in (("file-sync", "EIO", "reject-before"),
                                         ("file-sync", "EPERM", "reject-before"),
                                         ("parent-sync", "EIO", "reject-before"),
                                         ("write", "EIO", "partial-write")):
            fact = _fault(f"{kind}-{operation}-{code.lower()}", operation,
                          "parent" if operation == "parent-sync" else role, effect, code=code,
                          message=f"literal {'write-partial' if effect == 'partial-write' else operation} fault {code}",
                          **({"bytes": 2} if effect == "partial-write" else {}))
            cases.append(_case(f"{kind}-{operation}-{code.lower()}", kind, initial=None,
                               content="complete written payload\n", faults=[fact]))
    for kind in ("bootstrap", "append"):
        cases.append(_case(f"{kind}-write-zero", kind, initial=None, content="complete written payload\n", faults=[
            {**_fault(f"{kind}-write-zero", "write", "stage" if kind == "bootstrap" else "target", "zero-write", code=None), "message": None},
        ]))
    cases.extend([
        _case("cooperating-checked-replacements", initial="original\n", content=None, concurrency={
            "schedule": "checked-replacements", "writers": [
                {"id": "first", "content": "first writer\n"}, {"id": "second", "content": "second writer\n"},
            ],
        }),
        _case("exclusive-bootstrap-winner-during-staging", "bootstrap", initial=None, content=None, concurrency={
            "schedule": "exclusive-bootstrap", "writers": [
                {"id": "first", "content": "first complete bootstrap\n"}, {"id": "second", "content": "second complete bootstrap\n"},
            ],
        }),
    ])
    cases.extend([
        _case("committed-replacement-close-fails", faults=[_fault("r1-close", "close", "stage", "reject-after")]),
        _case("replacement-sync-and-close-fail", faults=[
            _fault("r2-sync", "file-sync", "stage"), _fault("r2-close", "close", "stage", "reject-after"),
        ]),
        _case("replacement-read-cleanup-and-close-fail", faults=[
            _fault("r3-read", "before-read", "target"), _fault("r3-cleanup", "cleanup", "stage"),
            _fault("r3-close", "close", "stage", "reject-after"),
        ]),
        _case("append-sync-and-close-fail", "append", initial="original\n", content="new\n", faults=[
            _fault("a1-sync", "file-sync", "target"), _fault("a1-close", "close", "target", "reject-after"),
        ]),
        _case("bootstrap-prepare-and-cleanup-fail", "bootstrap", initial=None, content="complete bootstrap\n", faults=[
            _fault("b1-sync", "file-sync", "stage"), _fault("b1-cleanup", "cleanup", "stage", "reject-after"),
        ]),
        _case("bootstrap-published-close-fails", "bootstrap", initial=None, content="complete bootstrap\n", faults=[
            _fault("b2-close", "close", "stage", "reject-after"),
        ]),
        _case("bootstrap-publication-lost-reply", "bootstrap", initial=None, content="complete bootstrap\n", faults=[
            _fault("b3-publish", "publish", "target", "reject-after"),
        ]),
        _case("bootstrap-publication-refused-indeterminate", "bootstrap", initial=None, content="complete bootstrap\n", faults=[
            _fault("b4-publish", "publish", "target"),
        ]),
        _case("bootstrap-foreign-stage-before-cleanup", "bootstrap", initial=None, content="complete bootstrap\n", faults=[
            _fault("b5-sync", "file-sync", "stage"),
            _fault("b5-foreign-stage", "cleanup", "stage", "replace-stage", code=None, externalContent="foreign stage winner\n"),
        ]),
    ])
    assert len(cases) == 41 and len({case["id"] for case in cases}) == 41
    return deepcopy(cases)
