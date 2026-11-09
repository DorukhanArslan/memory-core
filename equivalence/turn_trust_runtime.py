"""Literal model scripts exercise real SDK dispatch, trust, writer and storage owners."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from equivalence.get_contract import map_get_fixture_paths
from equivalence.session_contract import _catalog_sql
from equivalence.transcript_boundaries import _entry_payload, _error


def _owners(root, value):
    from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_corpus import MemoryCoreSessionCorpus

    agent, now = value.get("agentId", "main"), value["nowMs"]
    state = root / "state"
    path = state / "agents" / agent / "sessions" / "authority.sqlite"
    catalog = MemorySessionCatalog(path, agent_id=agent, clock_ms=lambda: now)
    ledger = MemoryArtifactProvenanceStore(root / "artifact-provenance.sqlite")
    corpus = MemoryCoreSessionCorpus(state, agent_id=agent, catalog=catalog,
                                    runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    return catalog, ledger, corpus


def _artifact_records(ledger, workspace):
    return [{"relativePath": path, "provenance": {
        "fileHash": value.file_hash, "originClass": value.origin_class, "observedAt": value.observed_at,
        **({"sessionId": value.session_id} if value.session_id is not None else {}),
        **({"sessionKey": value.session_key} if value.session_key is not None else {}),
    }} for path, value in ledger.list(workspace)]


def _files(workspace):
    return {str(path.relative_to(workspace)): path.read_text(encoding="utf-8")
            for path in workspace.rglob("*") if path.is_file()}


def _reopen(request):
    import memory_core

    root, value = Path(request["directory"]), request["input"]
    catalog, ledger, corpus = _owners(root, value)
    stored = catalog.read_transcript(value["sessionId"], session_key=value["sessionKey"])
    file, = corpus.discover_files()
    entry = corpus.read_index_entry(file)
    result = {"storedEvents": list(stored.events), "sourceEntry": _entry_payload(entry),
              "artifacts": _artifact_records(ledger, root / "workspace"), "files": _files(root / "workspace")}
    return {"result": result, "raw": {"pid": os.getpid(), "ppid": os.getppid(), "request": request,
                                       "implementationRoot": str(Path(memory_core.__file__).resolve().parents[1]),
                                       "sessionSql": _catalog_sql(catalog)}}


def run_turn_trust(arguments: dict[str, Any], *, evidence_directory: Path | None = None):
    from memory_core.turn_tool_dispatch import TurnTool, TurnToolDispatcher
    from memory_core.turn_trust import TurnTrust, build_tool_execution_error_result, build_tool_result_message

    value = deepcopy(arguments)
    if value.get("kind") != "turn-trust":
        raise ValueError("An actual turn-trust experiment requires its literal registry and scripts")
    with tempfile.TemporaryDirectory(prefix="python-turn-trust-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        workspace.mkdir()
        catalog, ledger, corpus = _owners(root, value)
        key, identifier, now = value["sessionKey"], value["sessionId"], value["nowMs"]
        catalog.upsert_session(key, {"sessionId": identifier, "updatedAt": now})
        raw = {"fixtureBase": str(root), "coordinatorPid": os.getpid(), "input": deepcopy(value),
               "toolObservations": [], "presentationObservations": [], "writes": [],
               "appends": [], "turns": [], "reopen": None}
        turns = []
        try:
            for turn in value["turns"]:
                trust = TurnTrust(turn["id"], sender_is_owner=turn.get("senderIsOwner"))
                for presentation in turn.get("presentationObservations", []):
                    before = trust.is_tainted()
                    trust.observe(presentation)
                    raw["presentationObservations"].append({
                        "origin": "trusted-host-presentation", "turnId": turn["id"],
                        "observation": deepcopy(presentation), "before": before, "after": trust.is_tainted(),
                    })
                observer = trust.write_observer(store=ledger, mutation_root=workspace, workspace_dir=workspace,
                                                session_id=identifier, session_key=key, now=lambda: now)
                sequence = 0
                attempts = []
                def append(message):
                    nonlocal sequence
                    event_id = f"{turn['id']}:message:{sequence}"
                    sequence += 1
                    result = catalog.append_message(identifier, message, session_key=key, event_id=event_id,
                                                     now_ms=now, cwd="/fixture/workspace")
                    raw["appends"].append({"turnId": turn["id"], "message": deepcopy(message),
                                           "eventId": event_id, "result": result})
                def write_memory(call_id, args):
                    relative = Path(args["path"])
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError("The literal write must remain in its owned workspace")
                    target = workspace / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    before = target.read_text() if target.exists() else ""
                    observer.write(absolute_path=target, content_before=before, content_after=args["content"],
                                   commit=lambda: target.write_text(args["content"], encoding="utf-8"))
                    raw["writes"].append({"turnId": turn["id"], "callId": call_id, "input": deepcopy(args),
                                           "before": before, "after": target.read_text(),
                                           "artifactRecords": _artifact_records(ledger, workspace)})
                    return deepcopy(value["writeResult"])
                registrations = [TurnTool("write_memory", write_memory)]
                sources = {"write_memory": None}
                for tool in value["tools"]:
                    def execute(_id, _args, *, facts=deepcopy(tool)):
                        if "error" in facts:
                            error = RuntimeError(facts["error"]["message"])
                            for field, field_value in facts["error"].items():
                                if field != "message":
                                    setattr(error, field, field_value)
                            raise error
                        return deepcopy(facts["result"])
                    sources[tool["name"]] = tool.get("resultContentSource")
                    registrations.append(TurnTool(tool["name"], execute, tool.get("resultContentSource")))
                for index, attempt in enumerate(turn["attempts"]):
                    observations = []
                    dispatcher = TurnToolDispatcher(trust, registrations, on_outcome=observations.append)
                    messages, outcomes = [], []
                    if index == 0:
                        message = deepcopy(turn["prompt"])
                        messages.append(message)
                        append(message)
                    for literal in attempt["responses"]:
                        message = trust.stamp_assistant(deepcopy(literal))
                        messages.append(message)
                        append(message)
                        for call in message["content"]:
                            if call.get("type") != "toolCall":
                                continue
                            try:
                                result = dispatcher.dispatch(call["name"], call["arguments"], tool_call_id=call["id"])
                                outcome = {"id": call["id"], "name": call["name"], "input": deepcopy(call["arguments"]),
                                           "result": deepcopy(result)}
                                failed = False
                            except Exception as error:
                                outcome = {"id": call["id"], "name": call["name"], "input": deepcopy(call["arguments"]),
                                           "error": _error(error)}
                                result = build_tool_execution_error_result(error)
                                failed = True
                            outcomes.append(outcome)
                            tool_message = build_tool_result_message(call, result, is_error=failed,
                                timestamp_ms=now, result_content_source=sources[call["name"]])
                            messages.append(tool_message)
                            append(tool_message)
                    snapshot = {"id": attempt["id"], "messages": messages, "toolOutcomes": outcomes,
                                "trust": {"tainted": trust.is_tainted()},
                                "artifacts": _artifact_records(ledger, workspace), "files": _files(workspace)}
                    attempts.append(snapshot)
                    raw["toolObservations"].append({"turnId": turn["id"], "attemptId": attempt["id"],
                                                     "origin": "dispatched-tool",
                                                     "observations": observations,
                                                     "writerOriginClass": trust.resolve_origin_class()})
                output = {"id": turn["id"], "attempts": attempts,
                          "trust": {"tainted": trust.is_tainted()}}
                turns.append(output)
                raw["turns"].append(deepcopy(output))
            request = {"directory": str(root), "input": value}
            wire = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
            process = subprocess.run([sys.executable, "-m", "equivalence.turn_trust_runtime", "--reopen"],
                input=wire, text=True, capture_output=True, cwd=Path(__file__).resolve().parents[1], check=False)
            raw["reopen"] = {"request": request, "stdout": process.stdout, "stderr": process.stderr,
                             "exitCode": process.returncode}
            if process.returncode:
                raise RuntimeError(f"The actual trust storage reopen failed: {process.stdout}\n{process.stderr}")
            reopened = json.loads(process.stdout)
            raw["reopen"]["raw"] = reopened["raw"]
            raw["sessionSql"] = _catalog_sql(catalog)
            return map_get_fixture_paths({"provider": "none", "turns": turns, **reopened["result"]}, root)
        finally:
            if evidence_directory is not None:
                evidence_directory = Path(evidence_directory)
                evidence_directory.mkdir(parents=True, exist_ok=True)
                (evidence_directory / "python-raw.json").write_text(
                    json.dumps([raw], ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    json.dump(_reopen(json.load(sys.stdin)), sys.stdout, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
