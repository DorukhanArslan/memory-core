"""Fresh-process durable-session experiment; every phase rereads real storage."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

from equivalence.durable_session_codec import map_durable_session_identities
from equivalence.get_contract import map_get_fixture_paths
from equivalence.transcript_boundaries import _entry_payload, _error


def run_durable_session_phase(request: dict[str, Any]) -> dict[str, Any]:
    import memory_core
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_context import build_session_context, convert_to_llm, is_session_history_prelude
    from memory_core.session_corpus import MemoryCoreSessionCorpus
    from memory_core.workspace import MemoryWorkspace
    from equivalence.importance_project import _logical_published
    from equivalence.session_contract import _catalog_sql

    value, phase, root = request["input"], request["phase"], Path(request["directory"])
    if phase["label"] not in {"write", "continue", "verify"} or not root.is_absolute():
        raise ValueError("A durable phase requires its explicit identity and persisted root")
    if phase["label"] == "verify" and (phase.get("sessions") or phase.get("appendMessages")):
        raise ValueError("The third process is a mutation-free catalog reopen")
    now, agent = phase.get("nowMs", value["nowMs"]), value.get("agentId", "main")
    state, workspace = root / "state", root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    store_path = state / "agents" / agent / "sessions" / "sessions.json"
    catalog = MemorySessionCatalog(store_path.parent / "session-authority.sqlite", agent_id=agent,
                                   store_path=store_path, clock_ms=lambda: now)
    corpus = MemoryCoreSessionCorpus(state, agent_id=agent, catalog=catalog,
                                    runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    raw: dict[str, Any] = {"label": phase["label"], "pid": os.getpid(), "ppid": os.getppid(),
                           "implementationRoot": str(Path(memory_core.__file__).resolve().parents[1]),
                           "fixtureBase": str(root), "request": deepcopy(request),
                           "sessionWrites": [], "appendWrites": [], "contextRequests": [], "sourceReads": [],
                           "queries": [], "storePaths": {"catalogStorePath": str(store_path),
                                                          "databasePath": str(catalog.path)}}
    for seed in phase.get("sessions", []):
        key, entry = seed.get("sessionKey", value["sessionKey"]), {"updatedAt": now, **deepcopy(seed["entry"])}
        result = catalog.upsert_session(key, entry)
        if "events" in seed:
            catalog.replace_events(entry["sessionId"], seed["events"], session_key=key)
        writes = [catalog.record_participant(key, {**participant, "promptedAt": participant.get("promptedAt", now),
                                                   "sessionAgentId": agent}) for participant in seed.get("participants", [])]
        snapshot = catalog.read_transcript(entry["sessionId"], session_key=key)
        raw["sessionWrites"].append({"key": key, "entry": entry, "result": result, "participantWrites": writes,
                                      "readBack": catalog.get_session_entry(key),
                                      "transcript": list(snapshot.events) if snapshot else None})
    appends = []
    for append in phase.get("appendMessages", []):
        key = append.get("sessionKey", value["sessionKey"])
        current = catalog.get_session_entry(key)
        identifier = append.get("sessionId", current.get("sessionId") if current else None)
        if not identifier or not append.get("eventId"):
            raise ValueError("Durable appends require a persisted current identity and caller event id")
        options = {"session_key": key, "event_id": append["eventId"], "now_ms": append.get("now", now),
                   "cwd": append.get("cwd", str(workspace)),
                   **({"parent_id": append["parentId"]} if "parentId" in append else {}),
                   **({"append_intent": append["appendIntent"]} if "appendIntent" in append else {})}
        try:
            result = catalog.append_message(identifier, append["message"], **options)
            output = {"id": append["eventId"], "result": result}
        except Exception as error:
            output = {"id": append["eventId"], "error": _error(error)}
        appends.append(output)
        raw["appendWrites"].append({"sessionId": identifier, "message": deepcopy(append["message"]),
                                     "options": options, **deepcopy(output)})
    config = MemoryConfig(workspace_dir=workspace, agent_id=agent,
                          store_path=state / "agents" / agent / "agent" / "openclaw-agent.sqlite",
                          session_search=True, search_max_results=200, search_min_score=0,
                          flags=FeatureFlags(vector_search=False, text_search=True, mmr=False, temporal_decay=False))
    store = SQLiteMemoryStore(config, None)
    owner_workspace = MemoryWorkspace(workspace, openclaw_state_dir=state, agent_id=agent,
                                       session_catalog=catalog, index_sources=["sessions"])
    raw["indexBeforeSync"] = store.read_published_index()
    raw["syncRequest"] = {"force": phase["label"] != "verify"}
    store.reindex(owner_workspace, force=phase["label"] != "verify")
    entries = corpus.discover_entries(include_content_revision=False, include_retained_sqlite=True)
    admitted = corpus.discover_admitted_entries()
    files = {(str(item.abs_path), item.session_id, item.artifact_kind): item for item in corpus.discover_files()}
    sources = []
    for source in admitted:
        file = files[(source["sessionFile"], source["sessionId"], source["artifactKind"])]
        entry = corpus.read_index_entry(file)
        output = {"source": source, "entry": _entry_payload(entry),
                  "resetRecallCutoff": entry.reset_recall_cutoff if entry else {"state": "absent"}}
        sources.append(output)
        raw["sourceReads"].append({"file": file.__dict__, "result": deepcopy(output)})

    def continuation(read):
        key = read.get("sessionKey", value["sessionKey"])
        current = catalog.get_session_entry(key)
        identifier = read.get("sessionId", current.get("sessionId") if current else None)
        actual = catalog.read_continuation(identifier, session_key=key) if identifier else None
        if actual:
            result = {"events": actual["events"], "visibleEvents": actual["visibleEvents"], "context": actual["context"],
                      "modelMessages": actual["llmMessages"], "preludeFlags": actual["historyPrelude"],
                      "modelPreludeFlags": actual["modelHistoryPrelude"]}
        else:
            context = build_session_context([])
            messages = convert_to_llm(context["messages"])
            result = {"events": [], "visibleEvents": [], "context": context, "modelMessages": messages,
                      "preludeFlags": [is_session_history_prelude(message) for message in context["messages"]],
                      "modelPreludeFlags": [is_session_history_prelude(message) for message in messages]}
        if current is not None:
            result["entry"] = current
        if "id" in read:
            result = {"id": read["id"], **result}
        raw["contextRequests"].append({"input": deepcopy(read), "sessionId": identifier, "actual": actual,
                                         "result": deepcopy(result)})
        return result

    main = continuation({})
    identity_reads = [continuation(read) for read in phase.get("identityReads", [])]
    queries = []
    for query in phase.get("queries", []):
        results = store.search(query["query"], max_results=query.get("maxResults", 200),
                               min_score=query.get("minScore", 0), sources={"sessions"})
        output = {"id": query["id"], "results": [result.to_payload() for result in results]}
        queries.append(output)
        raw["queries"].append({"input": deepcopy(query), **deepcopy(output)})
    full_sql = store.read_published_index()
    snapshot = {"label": phase["label"], **({"currentEntry": main["entry"]} if "entry" in main else {}),
                "instances": catalog.list_transcript_instances(), "catalog": entries, "admitted": admitted,
                "sourceEntries": sources, "participantRecords": catalog.list_participants(),
                **{key: main[key] for key in ("events", "visibleEvents", "context", "modelMessages", "preludeFlags", "modelPreludeFlags")},
                "identityReads": identity_reads, "appendResults": appends, "published": _logical_published(store),
                "indexSources": [{"path": row["path"], "source": row["source"]} for row in full_sql["sources"]],
                "queries": queries}
    if phase.get("anchorEntryId"):
        snapshot["activeAnchor"] = catalog.read_anchor(
            main.get("entry", {}).get("sessionId", value["sessionId"]), phase["anchorEntryId"], session_key=value["sessionKey"])
    raw["snapshot"] = {**deepcopy(snapshot), "sessionSql": _catalog_sql(catalog), "fullSql": full_sql}
    return {"result": map_get_fixture_paths(snapshot, root), "raw": raw}


def run_durable_sessions(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict[str, Any]:
    value = deepcopy(arguments)
    if value.get("kind") != "durable" or [phase.get("label") for phase in value.get("phases", [])] != ["write", "continue", "verify"]:
        raise ValueError("Durability requires exactly three fresh ordered OS processes")
    raw: dict[str, Any] = {"kind": "durable", "coordinatorPid": os.getpid(), "phases": []}
    results, paths = [], []
    identity = {key: item for key, item in value.items() if key != "phases"}
    with tempfile.TemporaryDirectory(prefix="python-durable-session-") as temporary:
        root = Path(temporary)
        raw["fixtureBase"] = str(root)
        try:
            for phase in value["phases"]:
                request = {"input": identity, "phase": phase, "directory": str(root)}
                wire = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
                record = {"label": phase["label"], "request": request, "requestJson": wire,
                          "requestSha256": hashlib.sha256(wire.encode()).hexdigest(), "startedAtNs": str(time.monotonic_ns())}
                # Each child imports the working checkout and receives only its own
                # literal instructions. Persisted storage is the sole shared state.
                process = subprocess.Popen([sys.executable, "-m", "equivalence.durable_sessions", "--phase"],
                                           cwd=Path(__file__).resolve().parents[1],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(wire)
                record.update(pid=process.pid, exit={"code": process.returncode, "signal": None},
                              finishedAtNs=str(time.monotonic_ns()), stdout=stdout, stderr=stderr)
                raw["phases"].append(record)
                if process.returncode:
                    raise RuntimeError(f"Durable {phase['label']} process failed: {stdout}\n{stderr}")
                output = json.loads(stdout)
                record["raw"] = output["raw"]
                results.append(output["result"])
                paths.append(map_get_fixture_paths(output["raw"]["storePaths"]["databasePath"], root))
        finally:
            if evidence_directory is not None:
                evidence_directory = Path(evidence_directory)
                evidence_directory.mkdir(parents=True, exist_ok=True)
                (evidence_directory / "python-raw.json").write_text(
                    json.dumps([raw], ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")
    return {"provider": "none", "phases": map_durable_session_identities(results, paths)}


if __name__ == "__main__":
    try:
        output = run_durable_session_phase(json.load(sys.stdin))
        json.dump(output, sys.stdout, ensure_ascii=False, default=str)
        sys.stdout.write("\n")
    except Exception as error:
        json.dump({"fatal": _error(error), "pid": os.getpid()}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        raise
