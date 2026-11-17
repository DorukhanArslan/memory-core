"""Reopen physical consolidation preimages and origin ledgers at settlement."""

from contextlib import closing
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from equivalence.deep_consolidation import FACT, KEPT, LINEAGE, OLD_FACT, OLD_KEY, validate_case
from equivalence.promotion_apply_family_evidence import require, same

_ORIGIN_FIELDS = {
    "entry_key": "entryKey", "agent_id": "agentId", "session_id": "sessionId",
    "session_key": "sessionKey", "origin_class": "originClass", "observed_at": "observedAt",
}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value):
    def object_pairs(pairs):
        result = dict(pairs)
        require(len(pairs) == len(result), "Duplicate property in persisted consolidation JSON")
        return result

    def invalid_constant(token):
        raise ValueError(f"Nonfinite number in persisted consolidation JSON: {token}")

    return json.loads(value, object_pairs_hook=object_pairs, parse_constant=invalid_constant)


def _table_rows(snapshot, filename, table, *, native):
    """Check the captured SQL rows against a private copy of the actual database and its WAL."""
    if table not in {"plugin_state_entries", "memory_entry_origins"}:
        raise ValueError("Unknown consolidation evidence table")
    if native:
        databases, path_key, files, data_key = snapshot["physical"], "path", snapshot["fsTree"], "bytes"
    else:
        databases, path_key = snapshot["sqlite"], "databasePath"
        files, data_key = snapshot["filesystem"], "hex"
    databases = [db for db in databases if db[path_key] == str(filename)]
    require(len(databases) == 1, f"Missing owned database for {table}")
    tables = [t for t in databases[0]["tables"] if t["name"] == table]
    require(len(tables) == 1, f"Missing captured table {table}")
    tree = {row["path"]: row for row in files}
    require(len(tree) == len(files), "Duplicate physical file")
    with TemporaryDirectory(prefix="deep-state-replay-") as tmp:
        target = Path(tmp) / "replay.sqlite"
        for suffix in ("", "-wal", "-journal"):
            entry = tree.get(str(filename) + suffix)
            if entry is None and suffix:
                continue
            require(entry is not None and entry["kind"] == "file", "Missing physical database bytes")
            Path(str(target) + suffix).write_bytes(bytes.fromhex(entry[data_key]))
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            selection = "*" if native else "rowid AS __rowid__,*"
            observed = [dict(row) for row in db.execute(f'SELECT {selection} FROM "{table}"')]
    # SQLite's SELECT without ORDER BY does not promise physical iteration order.
    def ordered(rows):
        return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, allow_nan=False))

    same(ordered(observed), ordered(tables[0]["rows"]), f"The captured {table} rows differ from the database bytes")
    return observed


def _sort_origins(rows):
    return sorted(rows, key=lambda row: (row["entryKey"], row["agentId"], row["sessionId"]))


def _origins(snapshot, root, agent, native):
    if native:
        database = root / "state" / "agents" / agent / "agent" / "openclaw-agent.sqlite"
    else:
        database = root / "agents" / agent / "memory.sqlite"
    rows = []
    for physical in _table_rows(snapshot, database, "memory_entry_origins", native=native):
        values = physical.copy()
        if not native:
            require(type(values.pop("__rowid__")) is int, "SDK origin lost its physical rowid")
        require(values.keys() == _ORIGIN_FIELDS.keys(), "Origin table column was lost or added")
        rows.append({_ORIGIN_FIELDS[k]: v for k, v in values.items()})
    return _sort_origins(rows)


def _backups(snapshot, raw, native):
    if native:
        workspace = raw["workspace"]
        workspace_key = _sha(workspace)
        entries = []
        for row in _table_rows(snapshot, Path(raw["databasePath"]), "plugin_state_entries", native=True):
            if row["namespace"] != "dreaming-memory-backups":
                continue
            require(row["plugin_id"] == "memory-core" and row["expires_at"] is None, "Foreign preimage row")
            wrapper = _json(row["value_json"])
            entry = wrapper["value"]
            key = entry["createdAt"] + ":" + entry["contentHash"][:12]
            same(wrapper, {"version": 1, "workspaceDir": workspace, "workspaceKey": workspace_key,
                           "key": key, "value": entry}, "Preimage carrier has the wrong key or workspace")
            same(row["entry_key"], workspace_key + ":" + _sha(key), "Preimage stored under another key")
            entries.append(entry)
    else:
        filename = Path(raw["fixtureBase"]) / "workspace/memory/.dreams/consolidation-preimages.json"
        files = [f for f in snapshot["filesystem"] if f["path"] == str(filename)]
        if not files:
            return []
        require(len(files) == 1 and files[0]["kind"] == "file", "Unexpected SDK preimage file")
        payload = _json(bytes.fromhex(files[0]["hex"]))
        require(type(payload["version"]) is int and payload["version"] == 1
                and set(payload) == {"version", "entries"}, "Malformed SDK preimage store")
        entries = payload["entries"]
    require(isinstance(entries, list), "Preimages must be a list")
    for entry in entries:
        require(set(entry) == {"createdAt", "content", "contentHash"}
                and _sha(entry["content"]) == entry["contentHash"], "Invalid persisted preimage or content digest")
    return entries


def _state(raw, case, native):
    def project(snapshot):
        return {"preimages": _backups(snapshot, raw, native),
                "origins": _origins(snapshot, Path(raw["fixtureBase"]), case["input"]["options"]["agentId"], native)}

    snapshots = raw["snapshots"]
    before, after = project(snapshots[0]), project(snapshots[1])
    if native:
        same(project(snapshots[2]), after, "An extra original API read mutated consolidation state")
    return {"before": before, "after": after}


def _check_original(case, raw, state):
    value = case["input"]
    branch = case["id"].removeprefix("deep-consolidation-")
    candidate = value["candidates"][0]
    key, path = candidate["key"], candidate["path"]
    timestamp = datetime.fromtimestamp(value["nowMs"] / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    initial_origins = _sort_origins(value["originSeeds"])
    same(state["before"], {"origins": initial_origins, "preimages": []}, "Physical setup differs from literal origin seeds")
    seed_calls = [c for c in raw["calls"] if c["operation"] == "recordMemoryEntryOrigins"]
    require(len(seed_calls) == 1, "Genuine original seed operation missing")
    same(seed_calls[0]["request"], {"agentId": value["options"]["agentId"], "origins": value["originSeeds"]},
         "Original origin seeding received different arguments")
    same(_sort_origins(seed_calls[0]["result"]), initial_origins, "Original did not insert both session origins")
    actual = raw["output"]
    documents = {d["path"]: d for d in actual["after"]["documents"]}
    for name in value["files"]:
        before = next(d for d in actual["before"]["documents"] if d["path"] == name)
        same(before["text"], value["files"][name], "Original file setup differs from literal bytes")
    same(documents[path]["text"], value["files"][path], "Model consolidation changed the original source")
    memory = documents["MEMORY.md"]["text"]
    dreams = documents["DREAMS.md"].get("text", "")
    initial_memory = value["files"]["MEMORY.md"]
    source = f"{path}#L{candidate['startLine']}-L{candidate['endLine']}"
    marker = f"<!-- openclaw-memory-promotion:{key} -->"
    result = actual["outcome"]["result"]
    require(result["applied"] == result["appended"] == 1 and result["rejectedCandidates"] == []
            and [r["key"] for r in result["appliedCandidates"]] == [key], "Candidate publication was not reached")
    require(marker in memory and all(line in memory.splitlines() for line in KEPT), "New or retained memory is missing")
    expected_origins = list(initial_origins)
    if branch in {"merged", "superseded"}:
        prior_origin = next(r for r in initial_origins if r["entryKey"] == OLD_KEY)
        expected_origins.append({**prior_origin, "entryKey": key})
    same(state["after"]["origins"], _sort_origins(expected_origins), "Unexpected original origin inheritance")
    if branch in {"added", "merged", "superseded"}:
        same(state["after"]["preimages"], [{"createdAt": timestamp, "content": initial_memory,
                                            "contentHash": _sha(initial_memory)}], "Original preimage missing or incorrect")
        require(f"Source: {source}" in memory and FACT in memory and OLD_KEY not in memory,
                "Consolidation did not replace the selected prior marker with a sourced candidate")
        require("## Memory Consolidation History" in dreams and f"### {timestamp}" in dreams
                and marker in dreams and all(f"- {action.title()}: {int(action == branch)}" in dreams.splitlines()
                                             for action in ("added", "merged", "superseded")),
                "Whole original history lacks the chosen action, timestamp, or source marker")
        if branch == "superseded":
            require(f"<!-- openclaw-memory-lineage:{LINEAGE} -->" in memory and OLD_FACT not in memory,
                    "Supersession retained the old fact or lost its lineage")
        return
    same(state["after"]["preimages"], [], "Rejected plan wrote a preimage")
    source_ref = f"{path}:{candidate['startLine']}-{candidate['endLine']}"
    require(memory.startswith(initial_memory.rstrip("\n")) and "## Promoted From Short-Term Memory" in memory
            and f"source={source_ref}]" in memory, "Rejected plan failed to preserve memory and append its sourced fallback")
    if branch == "concurrent-edit":
        edit = value["completion"]["mutationsBeforeReturn"][0]["text"]
        require(memory.startswith((initial_memory + edit).rstrip("\n")) and "- Fallback: append-only promotion." in dreams
                and "MEMORY.md changed while consolidation was running" in dreams, "Concurrent edit or skip history lost")
    else:
        require("## Memory Consolidation History" not in dreams, "A rejected plan published consolidation history")
        reason = {"unsafe-loss": "combined consolidation plan is invalid", "unrelated-prior": "unrelated prior entry",
                  "invalid-reply": "produced no structured output"}[branch]
        require(any(reason in str(c["args"]) for c in raw["calls"] if c["operation"] == "logger.warn"),
                "The requested loss, evidence, or malformed-plan rejection was not observed")


def compare_deep_state(case, native_raw, sdk_raw):
    """Extend the authenticated whole-apply result with physical state on both sides."""
    validate_case(case)
    native = _state(native_raw, case, True)
    sdk = _state(sdk_raw, case, False)
    _check_original(case, native_raw, native)
    same(sdk["before"], native["before"], "SDK did not start with the same physical origin rows and preimages")
    return native, sdk
