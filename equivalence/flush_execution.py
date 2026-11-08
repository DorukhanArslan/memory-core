"""Labelled model/tool sequences for actual memory-flush execution.

The model driver is a declared fixture boundary. Native admission, the agent's
tool loop, append/provenance owners and finalization are not replaced. Reviewed
non-warm cases cover execution outcomes only. The observed warm first-recall
policy difference remains visible and grants no acceptance credit.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import base64
import inspect
import json
from pathlib import Path
import re
import tempfile
from typing import Any


NOW_MS = 1777824000000
TARGET = "memory/2026-05-03.md"


def _write(content: str, *, path: str = "@target", identifier: str = "write-1") -> dict[str, Any]:
    return {"name": "write", "id": identifier, "arguments": {"path": path, "content": content}}


def _reply(*calls: dict[str, Any], text: str = "") -> dict[str, Any]:
    return {"text": text, "toolCalls": list(calls)}


def _step(label: str, *replies: dict[str, Any], cycle: int | None = None,
          **fields: Any) -> dict[str, Any]:
    return {"label": label, "replies": [*replies, _reply(text="NO_REPLY")],
            **({"entryPatch": {"compactionCount": cycle}} if cycle is not None else {}),
            **fields}


def build_flush_execution_cases() -> list[dict[str, Any]]:
    """Exercise bytes, ownership, final results and observable recall barriers."""
    cases: list[dict[str, Any]] = []

    def add(name: str, *, initial: str | None = None,
            steps: list[dict[str, Any]], **fields: Any) -> None:
        cases.append({
            "id": f"flush-execution-{name}", "requirement": "flush.execute-finalize",
            "operation": "flush-execution-runtime",
            "covers": [] if fields.get("warmIndex") else ["flush.execute-finalize.outcomes"],
            "input": {
                "nowMs": NOW_MS, "target": TARGET, "initialText": initial,
                "entry": {"sessionId": "source-session", "updatedAt": NOW_MS,
                          "compactionCount": 0, "totalTokens": 176000,
                          "totalTokensFresh": True, "totalTokensVersion": 1},
                "sessionKey": "agent:main:main", "untrusted": False,
                "sourceMessages": [
                    {"role": "user", "content": "Remember our project codename velvetkiwi."},
                    {"role": "assistant", "content": [
                        {"type": "text", "text": "I will remember velvetkiwi."},
                    ]},
                ],
                "steps": deepcopy(steps), "queries": ["velvetkiwi", "freshmangosteen"],
                **deepcopy(fields),
            },
            "driverScope": "same declared model/tool sequence through real native agent loop "
                           "and public Python HostKit; actual append/provenance/finalization",
            "normalizationPolicy": "Exact file bytes, write/read model receipts, owned cycle "
                                   "stamps, trust hashes and identity relationships are retained. "
                                   "Random internal run identities compare their relationship "
                                   "to the source and maintenance run; raw identities remain "
                                   "in diagnostics. First recall and explicit owner sync barriers "
                                   "are distinct observations, not interchangeable results.",
        })
        if fields.get("warmIndex"):
            cases[-1]["declaredDeviation"] = (
                "SDK dispatch completes its synchronous reindex before returning. Native warm "
                "search may read an earlier or newer published generation while detached "
                "maintenance proceeds. Every actual first-recall result remains compared; "
                "a later explicit sync does not establish first-recall equivalence. "
                "flush.execute-finalize.boundaries remains uncredited."
            )

    add("conditional-separators", initial="kept", steps=[
        _step("no-terminal-newline", _reply(_write("velvetkiwi"))),
        _step("leading-newline", _reply(_write("\nfreshmangosteen\n\n")), cycle=1),
        _step("existing-newline", _reply(_write("tail\r\n")), cycle=2),
        _step("unicode-bytes", _reply(_write("İstanbul 😀")), cycle=3),
    ])
    add("empty-and-whitespace", steps=[
        _step("empty-new-target", _reply(_write(""))),
        _step("spaces-crlf", _reply(_write("  \r\n")), cycle=1),
        _step("newline-only", _reply(_write("\n")), cycle=2),
    ])
    add("empty-existing-without-newline", initial="kept", steps=[
        _step("empty-existing", _reply(_write(""))),
        _step("later-trusted-write", _reply(_write("velvetkiwi")), cycle=1),
    ])
    add("no-reply-is-written-content", steps=[
        _step("exact-token", _reply(_write("NO_REPLY"))),
        _step("padded-token", _reply(_write("  NO_REPLY\n")), cycle=1),
        _step("ordinary-token-prefix", _reply(_write("NO_REPLY_FACTS: velvetkiwi")), cycle=2),
    ])
    add("sequential-tool-rounds", initial="seed\n", steps=[
        _step("two-writes-one-run",
              _reply(_write("velvetkiwi", identifier="first")),
              _reply(_write("freshmangosteen", identifier="second"))),
    ])
    add("read-before-append", initial="kept velvetkiwi\n", hostRead=True, steps=[
        _step("read-and-write",
              _reply({"name": "read", "id": "read-1", "arguments": {"path": "@target"}}),
              _reply(_write("freshmangosteen"))),
    ])
    add("tool-error-can-be-recovered", initial="kept\n", protectedFiles={
        "MEMORY.md": "Keep this existing long-term note.\n",
        "memory/other.md": "Keep this other daily note.\n",
    }, steps=[
        _step("wrong-path-then-correct",
              _reply(_write("must not escape", path="memory/other.md", identifier="bad")),
              _reply(_write("must not replace", path="MEMORY.md", identifier="bad-root")),
              _reply(_write("velvetkiwi", identifier="good"))),
    ])
    add("model-error-after-write", steps=[
        _step("write-survives-model-error", _reply(_write("velvetkiwi")),
              {"error": "fixture model failed"}),
    ])
    add("captured-compaction-cycle", steps=[
        _step("source-cycle-changes-during-run", _reply(_write("velvetkiwi")),
              duringRunEntryPatch={"compactionCount": 1}),
    ])
    add("cancel-before-write", steps=[
        _step("owner-cancels-before-write", {"cancel": True}),
    ])
    add("cancel-after-write", steps=[
        _step("owner-cancels-after-write", _reply(_write("velvetkiwi")), {"cancel": True}),
    ])
    add("model-failure-exhaustion", steps=[
        _step("failure-one", {"error": "fixture model failed"}),
        _step("failure-two", {"error": "fixture model failed"}),
        _step("failure-three", {"error": "fixture model failed"}),
        _step("same-cycle-suppressed", _reply(_write("must not be called"))),
        _step("next-cycle-success", _reply(_write("velvetkiwi")), cycle=1),
    ])
    add("maintenance-remains-untrusted", steps=[
        _step("owner-source-maintenance", _reply(_write("velvetkiwi"))),
        _step("tainted-source-maintenance", _reply(_write("tainted freshmangosteen")), cycle=1, untrusted=True),
        _step("owner-source-again", _reply(_write("later trusted")), cycle=2),
    ])
    add("external-edit-keeps-quarantine", steps=[
        _step("maintenance-write", _reply(_write("velvetkiwi"))),
        _step("external-edit", _reply(_write("freshmangosteen")), cycle=1,
              externalText="manual edit\n"),
    ])
    add("warm-index-first-recall", initial="obsoletekiwi\n", warmIndex=True,
        queries=["obsoletekiwi", "freshmangosteen"], steps=[
            _step("append-to-warm-index", _reply(_write("freshmangosteen"))),
        ])
    return cases


def _owned_entry(entry: Any) -> dict[str, Any]:
    fields = ("totalTokens", "totalTokensFresh", "totalTokensVersion", "compactionCount", "memoryFlush")
    return {field: deepcopy(entry[field]) for field in fields if field in entry}


def _tool_receipt(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Project the actual model receipt; never invent native ``changed`` evidence."""
    result: dict[str, Any] = {"name": name, "isError": payload.get("isError") is True}
    if "content" in payload:
        result["content"] = deepcopy(payload["content"])
        if "details" in payload:
            result["details"] = deepcopy(payload["details"])
    else:
        # This also makes the original SDK's missing native receipt observable in
        # baseline runs, instead of attributing a guessed changed=True to it.
        result["nativeReceiptSupported"] = False
        result["legacyPayload"] = deepcopy(payload)
    return result


def _query_rows(memory: Any, queries: list[str]) -> dict[str, Any]:
    rows = {}
    for query in queries:
        results = memory.store.search(query, max_results=20, min_score=0.0, sources={"memory"})
        rows[query] = {
            "available": True,
            "results": [{"path": hit.path, "startLine": hit.start_line,
                         "endLine": hit.end_line, "snippet": hit.snippet} for hit in results],
        }
    return rows


def _provenance_rows(store: Any, workspace: Path, source: Any, request: Any) -> list[dict[str, Any]]:
    records = []
    for path, record in store.list(workspace):
        records.append({
            "path": path, "fileHash": record.file_hash, "originClass": record.origin_class,
            "writer": {
                "internalSession": bool(record.session_id and record.session_id.startswith("internal-session-effects-")),
                "internalKey": bool(record.session_key and re.fullmatch(
                    r"agent:[^:]+:internal-session-effects:[^:]+", record.session_key,
                )),
                "sameSourceSession": record.session_id == source.session_id,
                "sameSourceKey": record.session_key == source.session_key,
                "matchesRunSession": record.session_id == getattr(request, "execution_session_id", None),
                "matchesRunKey": record.session_key == getattr(request, "execution_session_key", None),
            },
        })
    return sorted(records, key=lambda row: row["path"])


def run_flush_execution(arguments: dict[str, Any], *,
                        evidence_directory: Path | None = None) -> dict[str, Any]:
    """Drive public HostKit using the same declared provider replies as native.

    The host owns the scripted model and the optional generic read callback.
    Read is a real small-text host capability, not a claimed port of image or
    filesystem tool policy. Actual receipts and full raw records remain separate.
    """
    from memory_core.client import Memory
    from memory_core.config import MemoryConfig
    from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
    from memory_core.flags import FeatureFlags
    from memory_core.host import HostKit, SessionState
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

    supplied = deepcopy(arguments)
    snapshots: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="memory-flush-execution-") as temporary:
        directory = Path(temporary)
        workspace = directory / "workspace"
        workspace.mkdir()
        target = workspace / supplied.get("target", TARGET)
        if supplied.get("initialText") is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(supplied["initialText"].encode("utf-8"))
        for relative, text in supplied.get("protectedFiles", {}).items():
            file = workspace / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(text.encode("utf-8"))
        provenance = MemoryArtifactProvenanceStore(directory / "provenance.sqlite")
        memory = Memory.from_workspace(
            workspace,
            config=MemoryConfig(workspace_dir=workspace, flags=FeatureFlags(vector_search=False)),
            initialize=False, reindex=bool(supplied.get("warmIndex")), artifact_provenance=provenance,
        )
        source_messages = deepcopy(supplied.get("sourceMessages", []))
        source_file = directory / "source.json"
        source_file.write_text(json.dumps(source_messages, ensure_ascii=False), encoding="utf-8")
        source_before = source_file.read_bytes()
        source = SessionState(
            session_key=supplied.get("sessionKey", "agent:main:main"),
            session_id=supplied["entry"]["sessionId"], entry=supplied["entry"],
        )
        state_file = directory / "state.json"
        state_file.write_text(json.dumps(source.to_json(), ensure_ascii=False), encoding="utf-8")

        def host_read(params: Any) -> dict[str, Any]:
            path = Path(params["path"])
            resolved = (path if path.is_absolute() else workspace / path).resolve()
            resolved.relative_to(workspace.resolve())
            text = resolved.read_bytes().decode("utf-8", errors="replace")
            text = text.removeprefix("\ufeff").replace("\r\n", "\n")
            return {"content": [{"type": "text", "text": text}],
                    "details": {"kind": "text", "content": text}}

        kit_options: dict[str, Any] = {
            "now_ms": lambda: supplied.get("nowMs", NOW_MS), "timezone": "UTC",
            "artifact_provenance": provenance, "identity": OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        }
        if "flush_read_tool" in inspect.signature(HostKit).parameters:
            kit_options.update({
                "flush_read_tool": {
                    "name": "read", "description": "Read a text file.",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                                   "required": ["path"]},
                },
                "flush_read_dispatch": host_read,
            })
        kit = HostKit(memory, **kit_options)
        for step in supplied.get("steps", []):
            state = SessionState.from_json(json.loads(state_file.read_text(encoding="utf-8")))
            state = replace(state, entry={**dict(state.entry), **step.get("entryPatch", {})})
            if "externalText" in step:
                target.write_bytes(step["externalText"].encode("utf-8"))
            record = kit.prepare_flush(
                state, transcript=source_messages,
                untrusted_turn=step.get("untrusted", supplied.get("untrusted", False)),
            )
            request = record.flush
            receipts: list[dict[str, Any]] = []
            original_receipts: list[dict[str, Any]] = []
            model_calls = 0
            payloads: list[dict[str, Any]] = []
            cancelled = False
            outcome = None
            current = record.session
            if request is not None:
                for reply in step.get("replies", []):
                    model_calls += 1
                    if model_calls == 1 and "duringRunEntryPatch" in step:
                        current = replace(current, entry={**dict(current.entry), **step["duringRunEntryPatch"]})
                    if reply.get("error"):
                        payloads = [{"isError": True, "text": reply["error"]}]
                        break
                    if reply.get("cancel"):
                        cancelled = True
                        break
                    for call in reply.get("toolCalls", []):
                        params = deepcopy(call["arguments"])
                        if params.get("path") == "@target":
                            params["path"] = supplied.get("target", TARGET)
                        result = request.dispatch(call["name"], params)
                        original_receipts.append({"name": call["name"], "result": deepcopy(result)})
                        receipts.append(_tool_receipt(call["name"], result))
                complete_options = {}
                if payloads:
                    complete_options["payloads"] = payloads
                if cancelled:
                    complete_options["cancelled"] = True
                outcome = request.complete(current, **complete_options)
                current = outcome.session
            state_file.write_text(json.dumps(current.to_json(), ensure_ascii=False), encoding="utf-8")
            persisted = SessionState.from_json(json.loads(state_file.read_text(encoding="utf-8")))
            first_recall = _query_rows(memory, supplied.get("queries", [])) if supplied.get("warmIndex") else None
            memory.store.reindex(memory.workspace)
            after_sync = _query_rows(memory, supplied.get("queries", []))
            snapshot = {
                "label": step["label"],
                "outcome": "skipped" if request is None else "failed" if cancelled else
                "exhausted" if outcome.failure is not None and outcome.failure.exhausted else
                "failed" if outcome.failure is not None else "completed",
                "cancelled": bool(getattr(outcome, "cancelled", False)),
                "entry": _owned_entry(current.entry), "persistedEntry": _owned_entry(persisted.entry),
                "bytesBase64": base64.b64encode(target.read_bytes()).decode("ascii") if target.exists() else None,
                "protectedFiles": {
                    relative: base64.b64encode((workspace / relative).read_bytes()).decode("ascii")
                    if (workspace / relative).exists() else None
                    for relative in supplied.get("protectedFiles", {})
                },
                "toolsAvailable": sorted(tool["name"] for tool in request.tools) if request else [],
                "modelCalls": model_calls, "toolResults": receipts,
                "provenance": _provenance_rows(provenance, workspace, source, request),
                "sourceUnchanged": source_file.read_bytes() == source_before,
                "firstRecall": first_recall, "afterSyncRecall": after_sync,
            }
            snapshots.append(snapshot)
            raw.append({
                **deepcopy(snapshot), "session": current.to_json(), "persistedSession": persisted.to_json(),
                "request": None if request is None else {
                    "messages": request.messages, "tools": request.tools,
                    "runId": getattr(request, "run_id", None),
                    "executionSessionId": getattr(request, "execution_session_id", None),
                    "executionSessionKey": getattr(request, "execution_session_key", None),
                },
                "receipts": original_receipts, "modelPayloads": payloads, "callerCancelled": cancelled,
                "provenanceRaw": [{"path": path, **asdict(value)} for path, value in provenance.list(workspace)],
            })
        if evidence_directory is not None:
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(
                json.dumps(raw, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8",
            )
        return {"provider": "none", "snapshots": snapshots}
