"""Literal transcript-source experiments over real files and SQLite accessors."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from equivalence.get_contract import map_get_fixture_paths


def _error(error: BaseException) -> dict[str, Any]:
    return {"name": getattr(error, "name", type(error).__name__), "message": str(error),
            **{key: deepcopy(value) for key, value in vars(error).items() if key not in {"name", "stack"}}}


def _entry_payload(entry) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {**entry._extra, "hash": entry.hash, "content": entry.content, "lineMap": entry.line_map,
            "messageTimestampsMs": entry.message_timestamps_ms, "lineProvenance": entry.line_provenance,
            "sessionKind": entry.session_kind,
            **({"generatedByDreamingNarrative": True} if entry.generated_by_dreaming_narrative else {}),
            **({"generatedByCronRun": True} if entry.generated_by_cron_run else {})}


def run_transcript_boundary(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict[str, Any]:
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_artifacts import is_session_archive_artifact_name
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_corpus import MemoryCoreSessionCorpus, SessionCorpusFile

    value = deepcopy(arguments)
    if value.get("kind") != "boundary" or value.get("source") not in {"jsonl", "sqlite"}:
        raise ValueError("A transcript source experiment requires an explicit source kind")
    with tempfile.TemporaryDirectory(prefix="python-transcript-boundary-") as temporary:
        root = Path(temporary)
        now, agent = value["nowMs"], value.get("agentId", "main")
        identifier = value.get("sessionId", "boundary")
        key = value.get("sessionKey", f"agent:{agent}:dm:boundary")
        name = value.get("fileName", identifier + ".jsonl")
        if Path(name).name != name or "/" in agent or "\\" in agent:
            raise ValueError("Transcript source paths must remain owned")
        state = root / "state"
        directory = state / "agents" / agent / "sessions"
        directory.mkdir(parents=True)
        filename = directory / name
        catalog = MemorySessionCatalog(directory / "session-authority.sqlite", agent_id=agent,
                                       store_path=directory / "sessions.json", clock_ms=lambda: now)
        corpus = MemoryCoreSessionCorpus(state, agent_id=agent, catalog=catalog,
                                        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
        if value["source"] == "sqlite":
            catalog.upsert_session(key, {"sessionId": identifier, "updatedAt": now, **value.get("sessionEntry", {})})
        raw: dict[str, Any] = {"fixtureBase": str(root), "kind": "boundary", "source": value["source"],
                               "mutations": [], "reads": [], "sourceCaptures": []}

        def encode(item):
            if "rawBytes" in item:
                return bytes(item["rawBytes"])
            events = item.get("events", [])
            return ("\n".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) for event in events)
                    + ("\n" if events else "")).encode("utf-8")

        def write(item):
            if value["source"] == "sqlite":
                if "rawBytes" in item:
                    raise ValueError("SQLite mutations require actual event values")
                catalog.replace_events(identifier, item.get("events", []), session_key=key)
            else:
                payload = encode(item)
                if item.get("sameSize") and filename.stat().st_size != len(payload):
                    raise ValueError("The literal same-size mutation changed byte length")
                filename.write_bytes(payload)
                stamp = item.get("mtimeMs", now) / 1000
                os.utime(filename, (stamp, stamp))

        def capture():
            if value["source"] == "sqlite":
                snapshot = catalog.read_transcript(identifier, session_key=key)
                return {"entry": catalog.get_session_entry(key), "events": list(snapshot.events) if snapshot else None}
            try:
                stat = filename.lstat()
                result = {"filename": str(filename), "stat": {name: str(getattr(stat, "st_" + name))
                           for name in ("dev", "ino", "mode", "size", "mtime_ns", "ctime_ns")}}
                if filename.is_symlink():
                    result["target"] = os.readlink(filename)
                elif filename.is_file():
                    result["bytes"] = list(filename.read_bytes())
                return result
            except Exception as error:
                return {"filename": str(filename), "error": _error(error)}

        if "initial" in value:
            write(value["initial"])
            raw["mutations"].append({"op": "initial", "input": deepcopy(value["initial"])})
        reads = []
        for step in value.get("steps", [{"op": "read", "label": "initial"}]):
            op = step["op"]
            if op == "read":
                options = {"sessionKind": "interactive", **value.get("options", {}), **step.get("options", {})}
                is_sqlite = value["source"] == "sqlite"
                file = SessionCorpusFile(
                    rel_path=f"sessions/{agent}/{name}", abs_path=Path(key) if is_sqlite else filename,
                    session_key=key if is_sqlite else None, session_kind=options["sessionKind"],
                    session_id=identifier, transcript_source="sqlite" if is_sqlite else "file",
                    artifact_kind="archive-artifact" if is_session_archive_artifact_name(name) else "active-session",
                    store_path=str(catalog.store_path) if is_sqlite else None,
                    updated_at_ms=value.get("updatedAtMs", now) if is_sqlite else None,
                    generated_by_dreaming_narrative=options.get("generatedByDreamingNarrative", False),
                    generated_by_cron_run=options.get("generatedByCronRun", False),
                )
                observed = []
                def observe(message, timestamp_ms):
                    observed.append({"message": deepcopy(message), "timestampMs": timestamp_ms})
                    fact = step.get("observerError", value.get("observerError"))
                    if fact:
                        error = RuntimeError(fact["message"])
                        error.name = fact.get("name", "Error")
                        if "code" in fact:
                            error.code = fact["code"]
                        raise error
                callback = observe if value.get("observer") or step.get("observer") else None
                try:
                    entry = corpus.read_index_entry(file, on_transcript_message=callback)
                    result = {"label": step["label"], "entry": _entry_payload(entry),
                              **({"resetRecallCutoff": entry.reset_recall_cutoff} if entry else {}),
                              "observedMessages": observed}
                except Exception as error:
                    result = {"label": step["label"], "error": _error(error), "observedMessages": observed}
                reads.append(result)
                raw["reads"].append({"request": {"file": file.__dict__, "options": options,
                                                   "onTranscriptMessage": callback is not None}, "result": deepcopy(result)})
                raw["sourceCaptures"].append(capture())
            elif op in {"write", "replace-events"}:
                if op == "replace-events" and value["source"] != "sqlite":
                    raise ValueError("replace-events requires SQLite")
                write(step)
                raw["mutations"].append(deepcopy(step))
            elif op in {"remove", "directory", "symlink"}:
                if value["source"] != "jsonl":
                    raise ValueError("Filesystem mutation requires JSONL")
                if filename.is_symlink() or filename.is_file():
                    filename.unlink()
                elif filename.is_dir():
                    filename.rmdir()
                if op == "directory":
                    filename.mkdir()
                elif op == "symlink":
                    target = root / "symlink-target.jsonl"
                    target.write_bytes(encode(step))
                    stamp = step.get("mtimeMs", now) / 1000
                    os.utime(target, (stamp, stamp))
                    filename.symlink_to(target)
                raw["mutations"].append(deepcopy(step))
            else:
                raise ValueError(f"Unsupported transcript source mutation: {op}")
        if evidence_directory is not None:
            evidence_directory = Path(evidence_directory)
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=False, default=str, indent=2) + "\n")
        return map_get_fixture_paths({"provider": "none", "reads": reads}, root)
